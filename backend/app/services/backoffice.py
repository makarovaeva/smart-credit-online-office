"""Заявки глазами сотрудника банка: свои очереди, карточка, переназначение.

«Свои» заявки - назначенные на сотрудника и те, с которыми он уже работал (есть его действие
в истории статусов). Администратор видит все.
"""

import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ApplicationConsent,
    ApplicationStatusHistory,
    Company,
    CompanyOwner,
    CreditDecision,
    CreditMemo,
    Document,
    ExternalCheck,
    InfoRequest,
    PreApproval,
    ScoringResult,
    User,
)
from app.models.enums import ApplicationStatus, RiskZone, UserRole
from app.schemas.application import ConsentRead, PreApprovalRead, StatusHistoryItem
from app.schemas.backoffice import BackofficeApplicationDetail, BackofficeApplicationItem
from app.schemas.company import CompanyOwnerRead, CompanyRead
from app.schemas.decision import CreditMemoRead, ExternalCheckRead, ScoringResultRead
from app.schemas.document import DocumentRead, InfoRequestRead
from app.services.applications import to_read
from app.services.assignment import STAGE_ROLES
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from app.services.loans import get_contract, to_contract_read
from app.services.offers import to_decision_read


def _mine(user: User):
    processed = select(ApplicationStatusHistory.application_id).where(
        ApplicationStatusHistory.actor_id == user.id
    )
    return or_(Application.assignee_id == user.id, Application.id.in_(processed))


def _visible(query: Select, user: User) -> Select:
    return query if user.role == UserRole.ADMIN else query.where(_mine(user))


def _latest_scoring():
    return (
        select(
            ScoringResult.application_id,
            ScoringResult.risk_zone,
            ScoringResult.risk_grade,
        )
        .ext(distinct_on(ScoringResult.application_id))
        .order_by(ScoringResult.application_id, ScoringResult.created_at.desc())
        .subquery()
    )


async def list_queue(
    session: AsyncSession,
    user: User,
    *,
    statuses: list[ApplicationStatus] | None,
    risk_zone: RiskZone | None,
    limit: int,
    offset: int,
) -> tuple[list[BackofficeApplicationItem], int]:
    """Свои заявки сотрудника, старые первыми - в порядке очереди."""
    scoring = _latest_scoring()
    query = _visible(
        select(Application, Company.name, Company.inn, scoring.c.risk_zone, scoring.c.risk_grade)
        .join(Company, Company.id == Application.company_id)
        .outerjoin(scoring, scoring.c.application_id == Application.id),
        user,
    )
    if statuses:
        query = query.where(Application.status.in_(statuses))
    if risk_zone:
        query = query.where(scoring.c.risk_zone == risk_zone)

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(Application.created_at, Application.number).limit(limit).offset(offset)
    )
    items = [
        BackofficeApplicationItem.model_validate(
            _columns(application)
            | {
                "company_name": name,
                "company_inn": inn,
                "risk_zone": zone,
                "risk_grade": grade,
            }
        )
        for application, name, inn, zone, grade in rows
    ]
    return items, total or 0


def _columns(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in type(obj).__mapper__.column_attrs}


async def get_visible_application(
    session: AsyncSession, user: User, application_id: uuid.UUID, *, for_update: bool = False
) -> Application:
    query = _visible(select(Application).where(Application.id == application_id), user)
    if for_update:
        query = query.with_for_update()
    application = await session.scalar(query)
    if application is None:
        raise NotFoundError("Заявка не найдена")
    return application


async def _all(session: AsyncSession, model: Any, application_id: uuid.UUID) -> list[Any]:
    rows = await session.scalars(
        select(model).where(model.application_id == application_id).order_by(model.created_at)
    )
    return list(rows)


async def get_detail(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> BackofficeApplicationDetail:
    """Всё для решения одним запросом: данные, проверки, скоринг, AI Credit Memo, история."""
    application = await get_visible_application(session, user, application_id)
    company = await session.get(Company, application.company_id)
    assert company is not None
    owners = await session.scalars(
        select(CompanyOwner).where(CompanyOwner.company_id == company.id)
    )
    owners_read = [CompanyOwnerRead.model_validate(o) for o in owners]
    pre_approvals = await _all(session, PreApproval, application.id)
    scorings = await _all(session, ScoringResult, application.id)
    memos = await _all(session, CreditMemo, application.id)
    contract = await get_contract(session, application.id)

    return BackofficeApplicationDetail(
        application=await to_read(session, application),
        company=CompanyRead.model_validate(_columns(company) | {"owners": owners_read}),
        owners=owners_read,
        assignee_id=application.assignee_id,
        consents=[
            ConsentRead.model_validate(c)
            for c in await _all(session, ApplicationConsent, application.id)
        ],
        pre_approval=PreApprovalRead.model_validate(pre_approvals[-1]) if pre_approvals else None,
        external_checks=[
            ExternalCheckRead.model_validate(c)
            for c in await _all(session, ExternalCheck, application.id)
        ],
        scoring=ScoringResultRead.model_validate(scorings[-1]) if scorings else None,
        credit_memo=CreditMemoRead.model_validate(memos[-1]) if memos else None,
        decisions=[
            to_decision_read(d) for d in await _all(session, CreditDecision, application.id)
        ],
        contract=await to_contract_read(session, contract) if contract else None,
        info_requests=[
            InfoRequestRead.model_validate(r)
            for r in await _all(session, InfoRequest, application.id)
        ],
        documents=[
            DocumentRead.model_validate(d) for d in await _all(session, Document, application.id)
        ],
        history=[
            StatusHistoryItem.model_validate(h)
            for h in await _all(session, ApplicationStatusHistory, application.id)
        ],
    )


async def reassign(
    session: AsyncSession, user: User, application_id: uuid.UUID, assignee_id: uuid.UUID
) -> BackofficeApplicationDetail:
    """Передать заявку другому сотруднику той же роли (отпуск, перегрузка)."""
    application = await get_visible_application(session, user, application_id, for_update=True)
    role = STAGE_ROLES.get(application.status)
    if role is None:
        raise ConflictError("Заявка сейчас не на этапе аналитика или андеррайтера")
    if user.role not in (role, UserRole.ADMIN):
        raise ForbiddenError("Переназначить заявку может сотрудник этого этапа")
    assignee = await session.get(User, assignee_id)
    if assignee is None or not assignee.is_active or assignee.role != role:
        raise ValidationFailedError("Исполнитель должен быть активным сотрудником нужной роли")
    application.assignee_id = assignee.id
    await session.commit()
    # Новый исполнитель видит заявку, прежний - только если уже работал с ней
    return await get_detail(session, assignee, application_id)
