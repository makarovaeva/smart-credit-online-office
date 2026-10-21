"""Оффер и выдача. Подготовка договора, подписание и перечисление средств - симуляция."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, CreditDecision, User
from app.models.enums import ActorType, ApplicationStatus, CloseReason, DecisionType, OfferResponse
from app.schemas.decision import DecisionRead, OfferRead
from app.services.applications import get_client_application
from app.services.credit_policy import monthly_payment
from app.services.errors import ConflictError, NotFoundError
from app.services.transitions import transition

S = ApplicationStatus
OFFER_DECISIONS = (DecisionType.APPROVED, DecisionType.CONDITIONAL_APPROVAL)


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
    application = await get_client_application(session, user, application_id, for_update=True)
    decision = await _open_offer(session, application)
    decision.client_response = OfferResponse.ACCEPTED
    decision.client_responded_at = datetime.now(UTC)

    await transition(session, application, S.OFFER_ACCEPTED, ActorType.CLIENT, user.id)
    await transition(session, application, S.CONTRACT_GENERATION, ActorType.SYSTEM)
    await transition(
        session, application, S.E_SIGN, ActorType.SYSTEM, comment="Договор подготовлен"
    )
    await session.commit()
    return application


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
    """Код подтверждения не сверяется: в симуляции он показывается прямо в интерфейсе."""
    application = await get_client_application(session, user, application_id, for_update=True)
    await transition(
        session, application, S.DISBURSEMENT, ActorType.CLIENT, user.id, comment="Договор подписан"
    )
    await transition(
        session, application, S.COMPLETED, ActorType.SYSTEM, comment="Средства зачислены"
    )
    await session.commit()
    return application
