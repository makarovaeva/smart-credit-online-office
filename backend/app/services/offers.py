"""Оффер и выдача. Подготовка договора, подписание и перечисление средств - симуляция."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Application, CreditDecision, LoanContract, User
from app.models.enums import ActorType, ApplicationStatus, CloseReason, DecisionType, OfferResponse
from app.schemas.decision import DecisionRead, OfferRead
from app.services import loans
from app.services.applications import get_client_application
from app.services.credit_policy import monthly_payment
from app.services.decisions import ensure_assignee, get_application_for_update
from app.services.errors import ConflictError, NotFoundError
from app.services.status_machine import ensure_transition
from app.services.transitions import transition

S = ApplicationStatus
OFFER_DECISIONS = (DecisionType.APPROVED, DecisionType.CONDITIONAL_APPROVAL)
# Оффер уже принят: повторный accept возвращает текущее состояние или доводит прерванный шаг
AFTER_ACCEPT = frozenset(
    {S.OFFER_ACCEPTED, S.CONTRACT_GENERATION, S.E_SIGN, S.DISBURSEMENT, S.COMPLETED}
)


def _decision_data(decision: CreditDecision) -> dict:
    data = {c.key: getattr(decision, c.key) for c in CreditDecision.__mapper__.column_attrs}
    payment = None
    if decision.approved_amount and decision.approved_term_months and decision.interest_rate:
        payment = monthly_payment(
            decision.approved_amount, decision.approved_term_months, decision.interest_rate
        ).quantize(Decimal("0.01"))
    return data | {"estimated_monthly_payment": payment}


def to_offer_read(decision: CreditDecision) -> OfferRead:
    return OfferRead.model_validate(_decision_data(decision))


def to_decision_read(decision: CreditDecision) -> DecisionRead:
    return DecisionRead.model_validate(_decision_data(decision))


async def _latest_offer(session: AsyncSession, application_id: uuid.UUID) -> CreditDecision:
    decision = await session.scalar(
        select(CreditDecision)
        .where(
            CreditDecision.application_id == application_id,
            CreditDecision.decision_type.in_(OFFER_DECISIONS),
        )
        .order_by(CreditDecision.created_at.desc())
        .limit(1)
    )
    if decision is None:
        raise NotFoundError("Предложения банка по заявке нет")
    return decision


async def get_offer(session: AsyncSession, user: User, application_id: uuid.UUID) -> CreditDecision:
    application = await get_client_application(session, user, application_id)
    return await _latest_offer(session, application.id)


async def _open_offer(session: AsyncSession, application: Application) -> CreditDecision:
    if application.status != S.OFFER_GENERATED:
        raise ConflictError("Нет предложения, ожидающего ответа")
    decision = await _latest_offer(session, application.id)
    if decision.valid_until and decision.valid_until < datetime.now(UTC):
        raise ConflictError("Срок действия предложения истёк")
    return decision


async def accept_offer(session: AsyncSession, user: User, application_id: uuid.UUID) -> Application:
    """offer_generated -> offer_accepted -> contract_generation -> e_sign: договор и график
    готовятся сразу. Повторный вызов после принятия ничего не меняет."""
    application = await get_client_application(session, user, application_id, for_update=True)
    if application.status in AFTER_ACCEPT:
        decision = await _latest_offer(session, application.id)
    else:
        decision = await _open_offer(session, application)
        decision.client_response = OfferResponse.ACCEPTED
        decision.client_responded_at = datetime.now(UTC)
        await transition(session, application, S.OFFER_ACCEPTED, ActorType.CLIENT, user.id)

    if application.status == S.OFFER_ACCEPTED:
        await transition(session, application, S.CONTRACT_GENERATION, ActorType.SYSTEM)
    # В режиме analyst заявка ждёт кредитного аналитика на contract_generation
    if (
        application.status == S.CONTRACT_GENERATION
        and get_settings().contract_preparation == "auto"
    ):
        await _prepare(session, application, decision, ActorType.SYSTEM)
    await session.commit()
    return application


async def _prepare(
    session: AsyncSession,
    application: Application,
    decision: CreditDecision,
    actor: ActorType,
    actor_id: uuid.UUID | None = None,
) -> LoanContract:
    contract = await loans.prepare_contract(session, application, decision)
    await transition(
        session,
        application,
        S.E_SIGN,
        actor,
        actor_id,
        comment=f"Договор {contract.contract_number} подготовлен",
    )
    return contract


async def prepare_contract_by_analyst(
    session: AsyncSession, analyst: User, application_id: uuid.UUID
) -> LoanContract:
    """Кредитный аналитик готовит договор на условиях принятого оффера: contract_generation ->
    e_sign. Повторный вызов после подготовки возвращает тот же договор."""
    application = await get_application_for_update(session, application_id)
    if application.status != S.CONTRACT_GENERATION:
        contract = await loans.get_contract(session, application.id)
        if contract is not None:
            return contract
    ensure_transition(application.status, S.E_SIGN, ActorType.CREDIT_ANALYST)
    ensure_assignee(application, analyst)
    decision = await _latest_offer(session, application.id)
    contract = await _prepare(session, application, decision, ActorType.CREDIT_ANALYST, analyst.id)
    await session.commit()
    return contract


async def reject_offer(
    session: AsyncSession, user: User, application_id: uuid.UUID, reason: str | None
) -> Application:
    application = await get_client_application(session, user, application_id, for_update=True)
    decision = await _open_offer(session, application)
    decision.client_response = OfferResponse.REJECTED
    decision.client_responded_at = datetime.now(UTC)

    await transition(
        session, application, S.OFFER_REJECTED, ActorType.CLIENT, user.id, comment=reason
    )
    await transition(
        session,
        application,
        S.CLOSED,
        ActorType.SYSTEM,
        close_reason=CloseReason.OFFER_REJECTED,
    )
    await session.commit()
    return application


async def sign_agreement(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> Application:
    """e_sign -> disbursement -> completed: подпись, открытие ссудного счёта, зачисление.
    Код подтверждения не сверяется - в симуляции он показывается в интерфейсе.
    Если выдача прервалась, повторный вызов её доводит; после выдачи - ничего не меняет."""
    application = await get_client_application(session, user, application_id, for_update=True)
    if application.status == S.COMPLETED:
        return application
    if application.status not in (S.E_SIGN, S.DISBURSEMENT):
        raise ConflictError("Договор ещё не готов к подписанию")

    contract = await loans.get_contract(session, application.id)
    if contract is None:
        # Заявка дошла до подписания до появления договоров - готовим его сейчас
        decision = await _latest_offer(session, application.id)
        contract = await loans.prepare_contract(session, application, decision)
    if application.status == S.E_SIGN:
        loans.sign_contract(contract)
        await transition(
            session,
            application,
            S.DISBURSEMENT,
            ActorType.CLIENT,
            user.id,
            comment=f"Договор {contract.contract_number} подписан",
        )
        # Подпись сохраняется, даже если выдача не пройдёт
        await session.commit()

    await loans.disburse(session, application, contract)
    await transition(
        session,
        application,
        S.COMPLETED,
        ActorType.SYSTEM,
        comment=f"Средства зачислены на счёт {contract.settlement_account_number}",
    )
    await session.commit()
    return application
