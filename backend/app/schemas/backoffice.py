import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import InternalRequestStatus, RiskGrade, RiskZone, UserRole
from app.schemas.application import (
    ApplicationRead,
    ApplicationShort,
    ConsentRead,
    PreApprovalRead,
    StatusHistoryItem,
)
from app.schemas.common import ORMModel
from app.schemas.company import CompanyOwnerRead, CompanyRead
from app.schemas.decision import (
    CreditMemoRead,
    DecisionRead,
    ExternalCheckRead,
    ScoringResultRead,
)
from app.schemas.document import DocumentRead, InfoRequestRead
from app.schemas.loan import LoanContractRead


class BackofficeApplicationItem(ApplicationShort):
    company_name: str
    company_inn: str
    assignee_id: uuid.UUID | None
    risk_grade: RiskGrade | None
    risk_zone: RiskZone | None
    expertise_request: InternalRequestStatus | None = Field(
        default=None,
        description="Активный запрос экспертизы андеррайтера (open / accepted): на вкладке "
        "«Запросы от андеррайтера», без него эскалация - «Новые эскалации» от ИИ",
    )


class InternalRequestRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    from_user_id: uuid.UUID
    accepted_by_id: uuid.UUID | None
    status: InternalRequestStatus
    message: str
    response_comment: str | None
    created_at: datetime
    accepted_at: datetime | None
    closed_at: datetime | None


class ReturnRequestBody(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class BackofficeApplicationDetail(BaseModel):
    """Карточка заявки для аналитика и андеррайтера: всё для решения одним запросом."""

    application: ApplicationRead
    company: CompanyRead
    owners: list[CompanyOwnerRead]
    assignee_id: uuid.UUID | None
    consents: list[ConsentRead]
    pre_approval: PreApprovalRead | None
    external_checks: list[ExternalCheckRead]
    scoring: ScoringResultRead | None
    credit_memo: CreditMemoRead | None
    decisions: list[DecisionRead]
    contract: LoanContractRead | None
    info_requests: list[InfoRequestRead]
    internal_requests: list[InternalRequestRead]
    documents: list[DocumentRead]
    history: list[StatusHistoryItem]
    staff: dict[uuid.UUID, str] = Field(
        default={}, description="Имена сотрудников, упомянутых в карточке (исполнитель, решения)"
    )


class EmployeeRead(BaseModel):
    id: uuid.UUID
    full_name: str
    role: UserRole
    # Заявок сейчас в работе на этапе сотрудника
    active_applications: int


class AssignRequest(BaseModel):
    assignee_id: uuid.UUID
