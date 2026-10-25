"""Заявки глазами клиента: черновик, согласия, подача, отказ после предварительного расчёта."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ApplicationConsent,
    ApplicationStatusHistory,
    CompanyMember,
    CreditDecision,
    CreditProduct,
    PreApproval,
    User,
)
from app.models.application import application_number_seq
from app.models.enums import (
    ActorType,
    ApplicationStatus,
    CloseReason,
    ConsentType,
    DecisionType,
    LoanPurpose,
)
from app.schemas.application import (
    ApplicationAction,
    ApplicationCreate,
    ApplicationRead,
    ApplicationUpdate,
    ClientStatus,
)
from app.services import pipeline
from app.services.client_status import client_status
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError
from app.services.transitions import transition

S = ApplicationStatus
A = ApplicationAction

CLIENT_ACTIONS: dict[ApplicationStatus, list[ApplicationAction]] = {
    S.DRAFT: [A.EDIT, A.GIVE_CONSENTS, A.UPLOAD_DOCUMENTS],
    S.PRE_APPROVED: [A.EDIT, A.SUBMIT, A.DECLINE_PRE_APPROVAL, A.UPLOAD_DOCUMENTS],
    S.NEED_ADDITIONAL_DATA: [A.EDIT, A.UPLOAD_DOCUMENTS, A.ANSWER_INFO_REQUEST],
    S.OFFER_GENERATED: [A.ACCEPT_OFFER, A.REJECT_OFFER],
    S.E_SIGN: [A.SIGN],
    # Подписано, но выдача прервалась - повторный sign её доводит
    S.DISBURSEMENT: [A.SIGN],
}

# Параметры кредита меняются только до подачи; по дозапросу - финансы и залог
TERMS_EDITABLE = frozenset({S.DRAFT, S.PRE_APPROVED})
DATA_EDITABLE = TERMS_EDITABLE | {S.NEED_ADDITIONAL_DATA}
TERMS_FIELDS = frozenset({"product_id", "requested_amount", "requested_term_months", "purpose"})
NOT_NULLABLE_FIELDS = TERMS_FIELDS | {"has_collateral"}
COLLATERAL_FIELDS = (
    "collateral_type",
    "collateral_description",
    "collateral_address",
    "collateral_market_value",
    "collateral_encumbrances",
)

REQUIRED_CONSENTS = frozenset(ConsentType)

_DESCRIPTIONS: dict[ApplicationStatus, str] = {
    S.DRAFT: "Черновик: заполните параметры кредита и дайте согласия на получение данных",
    S.DATA_COLLECTION: "Собираем данные о бизнесе и рассчитываем предварительные условия",
    S.PRE_APPROVED: "Предварительный расчёт готов: проверьте условия и отправьте заявку",
    S.SUBMITTED: "Заявка создана",
    S.NEED_ADDITIONAL_DATA: "Нужны дополнительные документы - посмотрите запросы банка",
    S.ANALYST_ESCALATION: "Требуется дополнительный анализ",
    S.ANALYST_COMPLETED: "Идет рассмотрение заявки",
    S.OFFER_ACCEPTED: "Условия приняты, готовим договор",
    S.CONTRACT_GENERATION: "Условия приняты, готовим договор",
    S.E_SIGN: "Договор готов: подпишите его электронной подписью",
    S.DISBURSEMENT: "Договор подписан, зачисляем средства",
    S.COMPLETED: "Средства зачислены на расчётный счёт",
    S.OFFER_REJECTED: "Вы не приняли предложение банка",
}
_CLOSED_DESCRIPTIONS: dict[CloseReason, str] = {
    CloseReason.PRE_APPROVAL_DECLINED: "Заявка закрыта: вы не стали продолжать",
    CloseReason.AUTO_DECLINED: "К сожалению, банк не готов предоставить финансирование",
    CloseReason.UNDERWRITER_DECLINED: "К сожалению, банк не готов предоставить финансирование",
    CloseReason.OFFER_REJECTED: "Заявка закрыта: вы не приняли предложение банка",
}


def _status_description(application: Application, status: ClientStatus) -> str:
    if application.status == S.CLOSED and application.close_reason:
        return _CLOSED_DESCRIPTIONS[application.close_reason]
    if application.status == S.OFFER_GENERATED:
        if status == ClientStatus.COUNTER_OFFER:
            return "Банк готов предоставить финансирование на измененных условиях"
        return "Заявка одобрена: посмотрите предложение банка"
    return _DESCRIPTIONS.get(application.status, "Идет рассмотрение заявки")


async def last_decision_type(
    session: AsyncSession, application_id: uuid.UUID
) -> DecisionType | None:
    return await session.scalar(
        select(CreditDecision.decision_type)
        .where(CreditDecision.application_id == application_id)
        .order_by(CreditDecision.created_at.desc())
        .limit(1)
    )


async def to_read(session: AsyncSession, application: Application) -> ApplicationRead:
    status = client_status(application.status, await last_decision_type(session, application.id))
    data = {c.key: getattr(application, c.key) for c in Application.__mapper__.column_attrs}
    return ApplicationRead.model_validate(
        data
        | {
            "client_status": status,
            "status_description": _status_description(application, status),
            "available_actions": CLIENT_ACTIONS.get(application.status, []),
        }
    )


def _member_companies(user: User):
    return select(CompanyMember.company_id).where(CompanyMember.user_id == user.id)


async def get_client_application(
    session: AsyncSession, user: User, application_id: uuid.UUID, *, for_update: bool = False
) -> Application:
    """Заявка компании, в которой состоит пользователь. Чужая - 404."""
    query = select(Application).where(
        Application.id == application_id, Application.company_id.in_(_member_companies(user))
    )
    if for_update:
        query = query.with_for_update()
    application = await session.scalar(query)
    if application is None:
        raise NotFoundError("Заявка не найдена")
    return application


def _check_product(
    product: CreditProduct | None, amount: Any, term_months: int, purpose: LoanPurpose
) -> None:
    if product is None or not product.is_active:
        raise ValidationFailedError("Кредитный продукт не найден")
    if purpose not in product.purposes:
        raise ValidationFailedError("Продукт не подходит для этой цели кредита")
    if not product.min_amount <= amount <= product.max_amount:
        raise ValidationFailedError(
            f"Сумма должна быть от {product.min_amount} до {product.max_amount}"
        )
    if not product.min_term_months <= term_months <= product.max_term_months:
        raise ValidationFailedError(
            f"Срок должен быть от {product.min_term_months} до {product.max_term_months} мес."
        )


def _clear_collateral_if_absent(application: Application) -> None:
    if not application.has_collateral:
        for field in COLLATERAL_FIELDS:
            setattr(application, field, None)


async def create_application(
    session: AsyncSession, user: User, body: ApplicationCreate
) -> Application:
    is_member = await session.scalar(
        select(func.count())
        .select_from(CompanyMember)
        .where(CompanyMember.company_id == body.company_id, CompanyMember.user_id == user.id)
    )
    if not is_member:
        raise NotFoundError("Компания не найдена")
    product = await session.get(CreditProduct, body.product_id)
    _check_product(product, body.requested_amount, body.requested_term_months, body.purpose)

    number = await session.scalar(select(application_number_seq.next_value()))
    application = Application(
        **body.model_dump(),
        number=f"CR-{datetime.now(UTC).year}-{number:06d}",
        applicant_id=user.id,
        status=S.DRAFT,
    )
    _clear_collateral_if_absent(application)
    session.add(application)
    await session.commit()
    return application


async def list_applications(
    session: AsyncSession,
    user: User,
    *,
    statuses: list[ApplicationStatus] | None,
    company_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[Application], int]:
    query = select(Application).where(Application.company_id.in_(_member_companies(user)))
    if statuses:
        query = query.where(Application.status.in_(statuses))
    if company_id:
        query = query.where(Application.company_id == company_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    items = await session.scalars(
        query.order_by(Application.created_at.desc(), Application.number.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), total or 0


async def update_application(
    session: AsyncSession, user: User, application_id: uuid.UUID, body: ApplicationUpdate
) -> Application:
    application = await get_client_application(session, user, application_id, for_update=True)
    if body.version != application.version:
        raise ConflictError("Заявка изменилась, обновите данные")
    if application.status not in DATA_EDITABLE:
        raise ConflictError("Заявку нельзя изменить на текущем этапе")

    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if changes.keys() & TERMS_FIELDS and application.status not in TERMS_EDITABLE:
        raise ConflictError("Параметры кредита нельзя изменить после подачи заявки")
    if empty := sorted(k for k in changes.keys() & NOT_NULLABLE_FIELDS if changes[k] is None):
        raise ValidationFailedError(f"Поля не могут быть пустыми: {', '.join(empty)}")

    for field, value in changes.items():
        setattr(application, field, value)
    if changes.keys() & TERMS_FIELDS:
        product = await session.get(CreditProduct, application.product_id)
        _check_product(
            product,
            application.requested_amount,
            application.requested_term_months,
            application.purpose,
        )
    _clear_collateral_if_absent(application)
    await session.commit()
    return application


async def give_consents(
    session: AsyncSession, user: User, application_id: uuid.UUID, types: list[ConsentType]
) -> Application:
    """Согласия на получение данных; когда даны все - черновик уходит в сбор данных."""
    application = await get_client_application(session, user, application_id, for_update=True)
    if application.status != S.DRAFT:
        raise ConflictError("Согласия даются только в черновике")

    existing: set[ConsentType] = set(
        await session.scalars(
            select(ApplicationConsent.type).where(
                ApplicationConsent.application_id == application.id
            )
        )
    )
    if missing := REQUIRED_CONSENTS - existing - set(types):
        raise ValidationFailedError(f"Нужны все согласия, не хватает: {', '.join(sorted(missing))}")
    for consent_type in set(types) - existing:
        session.add(
            ApplicationConsent(
                application_id=application.id, type=consent_type, granted_by_id=user.id
            )
        )
    await transition(session, application, S.DATA_COLLECTION, ActorType.CLIENT, user.id)
    await session.commit()
    await pipeline.run_safely(session, application, pipeline.run_data_collection)
    return application


async def list_consents(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> list[ApplicationConsent]:
    application = await get_client_application(session, user, application_id)
    consents = await session.scalars(
        select(ApplicationConsent)
        .where(ApplicationConsent.application_id == application.id)
        .order_by(ApplicationConsent.created_at)
    )
    return list(consents)


async def get_pre_approval(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> PreApproval:
    application = await get_client_application(session, user, application_id)
    pre_approval = await session.scalar(
        select(PreApproval)
        .where(PreApproval.application_id == application.id)
        .order_by(PreApproval.created_at.desc())
        .limit(1)
    )
    if pre_approval is None:
        raise NotFoundError("Предварительный расчёт ещё не готов")
    return pre_approval


async def decline_pre_approval(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> Application:
    application = await get_client_application(session, user, application_id, for_update=True)
    await transition(
        session,
        application,
        S.CLOSED,
        ActorType.CLIENT,
        user.id,
        close_reason=CloseReason.PRE_APPROVAL_DECLINED,
    )
    await session.commit()
    return application


async def submit_application(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> Application:
    application = await get_client_application(session, user, application_id, for_update=True)
    if application.status == S.PRE_APPROVED:
        product = await session.get(CreditProduct, application.product_id)
        if product is not None and product.requires_collateral and not application.has_collateral:
            raise ValidationFailedError("Для этого продукта нужен залог")
        if application.has_collateral and not (
            application.collateral_type and application.collateral_market_value
        ):
            raise ValidationFailedError("Укажите тип и рыночную стоимость залога")
    await transition(session, application, S.SUBMITTED, ActorType.CLIENT, user.id)
    await session.commit()
    await pipeline.run_safely(session, application, pipeline.run_assessment)
    return application


async def get_history(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> list[ApplicationStatusHistory]:
    application = await get_client_application(session, user, application_id)
    history = await session.scalars(
        select(ApplicationStatusHistory)
        .where(ApplicationStatusHistory.application_id == application.id)
        .order_by(ApplicationStatusHistory.created_at)
    )
    return list(history)
