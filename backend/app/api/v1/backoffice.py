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
    not_implemented,
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

router = APIRouter(
    prefix="/backoffice/applications", tags=["backoffice"], responses=AUTH_RESPONSES | NOT_FOUND
)


@router.get("")
async def list_applications(
    employee: CurrentEmployee,
    status_in: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    risk_zone: RiskZone | None = None,
    assignee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[BackofficeApplicationItem]:
    """Очередь заявок, старые первыми. Аналитику по умолчанию - analyst_escalation
    (жёлтая зона и запросы экспертизы от андеррайтера), андеррайтеру - underwriter_review."""
    not_implemented()


@router.get("/{application_id}")
async def get_application(
    application_id: uuid.UUID, employee: CurrentEmployee
) -> BackofficeApplicationDetail:
    """Карточка заявки: данные, проверки, метрики, скоринг, AI Credit Memo, история."""
    not_implemented()


@router.post("/{application_id}/assign", responses=CONFLICT)
async def assign(
    application_id: uuid.UUID, body: AssignRequest, employee: CurrentEmployee
) -> BackofficeApplicationDetail:
    not_implemented()


@router.post("/{application_id}/analyst-conclusion", responses=CONFLICT)
async def complete_analysis(
    application_id: uuid.UUID, body: AnalystConclusionRequest, analyst: CurrentAnalyst
) -> CreditMemoRead:
    """Заключение кредитного аналитика дописывается в AI Credit Memo (или обновляется
    по запросу андеррайтера): analyst_escalation -> analyst_completed -> underwriter_review."""
    not_implemented()


@router.post("/{application_id}/decision", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def make_decision(
    application_id: uuid.UUID, body: UnderwriterDecisionRequest, underwriter: CurrentUnderwriter
) -> DecisionRead:
    """Финальное решение андеррайтера по AI Credit Memo и/или заключению аналитика:
    approved / conditional_approval (контр-предложение) -> offer_generated,
    more_information_required + client -> need_additional_data (дозапрос формирует ИИ),
    more_information_required + credit_analyst -> analyst_escalation,
    declined -> closed."""
    not_implemented()
