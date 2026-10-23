import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AUTH_RESPONSES,
    CONFLICT,
    NOT_FOUND,
    CurrentAnalyst,
    CurrentEmployee,
    CurrentUnderwriter,
    Limit,
    Offset,
    SessionDep,
)
from app.models.enums import ApplicationStatus, RiskZone
from app.schemas.backoffice import (
    AssignRequest,
    BackofficeApplicationDetail,
    BackofficeApplicationItem,
)
from app.schemas.common import Page
from app.schemas.decision import (
    AnalystConclusionRequest,
    CreditMemoRead,
    DecisionRead,
    UnderwriterDecisionRequest,
)
from app.services import backoffice, decisions
from app.services.offers import to_decision_read

router = APIRouter(
    prefix="/backoffice/applications", tags=["backoffice"], responses=AUTH_RESPONSES | NOT_FOUND
)


@router.get("")
async def list_applications(
    employee: CurrentEmployee,
    session: SessionDep,
    status_in: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    risk_zone: RiskZone | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[BackofficeApplicationItem]:
    """Свои заявки сотрудника, старые первыми: назначенные на него и те, с которыми он уже
    работал. Заявка назначается автоматически: на analyst_escalation - аналитику,
    на underwriter_review - андеррайтеру. Текущая очередь аналитика - status=analyst_escalation,
    андеррайтера - status=underwriter_review. Администратор видит все заявки."""
    items, total = await backoffice.list_queue(
        session, employee, statuses=status_in, risk_zone=risk_zone, limit=limit, offset=offset
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{application_id}")
async def get_application(
    application_id: uuid.UUID, employee: CurrentEmployee, session: SessionDep
) -> BackofficeApplicationDetail:
    """Карточка своей заявки: данные, проверки, метрики, скоринг, AI Credit Memo, история."""
    return await backoffice.get_detail(session, employee, application_id)


@router.post("/{application_id}/assign", responses=CONFLICT)
async def assign(
    application_id: uuid.UUID, body: AssignRequest, employee: CurrentEmployee, session: SessionDep
) -> BackofficeApplicationDetail:
    """Передать заявку другому сотруднику той же роли. Доступно сотруднику текущего этапа
    и администратору."""
    return await backoffice.reassign(session, employee, application_id, body.assignee_id)


@router.post("/{application_id}/analyst-conclusion", responses=CONFLICT)
async def complete_analysis(
    application_id: uuid.UUID,
    body: AnalystConclusionRequest,
    analyst: CurrentAnalyst,
    session: SessionDep,
) -> CreditMemoRead:
    """Заключение кредитного аналитика дописывается в AI Credit Memo (или обновляется
    по запросу андеррайтера): analyst_escalation -> analyst_completed -> underwriter_review."""
    memo = await decisions.complete_analysis(session, analyst, application_id, body)
    return CreditMemoRead.model_validate(memo)


@router.post("/{application_id}/decision", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def make_decision(
    application_id: uuid.UUID,
    body: UnderwriterDecisionRequest,
    underwriter: CurrentUnderwriter,
    session: SessionDep,
) -> DecisionRead:
    """Финальное решение андеррайтера по AI Credit Memo и/или заключению аналитика:
    approved / conditional_approval (контр-предложение) -> offer_generated,
    more_information_required + client -> need_additional_data (дозапрос формирует ИИ),
    more_information_required + credit_analyst -> analyst_escalation,
    declined -> closed."""
    decision = await decisions.make_decision(session, underwriter, application_id, body)
    return to_decision_read(decision)
