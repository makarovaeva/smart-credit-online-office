import uuid

from pydantic import BaseModel

from app.models.enums import RiskGrade, RiskZone
from app.schemas.application import (
    ApplicationRead,
    ApplicationShort,
    ConsentRead,
    PreApprovalRead,
    StatusHistoryItem,
)
from app.schemas.company import CompanyOwnerRead, CompanyRead
from app.schemas.decision import (
    CreditMemoRead,
    DecisionRead,
    ExternalCheckRead,
    ScoringResultRead,
)
from app.schemas.document import DocumentRead, InfoRequestRead


class BackofficeApplicationItem(ApplicationShort):
    company_name: str
    company_inn: str
    assignee_id: uuid.UUID | None
    risk_grade: RiskGrade | None
    risk_zone: RiskZone | None


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
    info_requests: list[InfoRequestRead]
    documents: list[DocumentRead]
    history: list[StatusHistoryItem]


class AssignRequest(BaseModel):
    assignee_id: uuid.UUID
