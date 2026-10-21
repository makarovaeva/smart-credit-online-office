import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

from app.models.enums import ActorType, ApplicationStatus, CollateralType, ConsentType, LoanPurpose
from app.schemas.common import MoneyAmount, ORMModel, TermMonths

OptionalMoney = Annotated[Decimal | None, Field(ge=0, max_digits=15, decimal_places=2)]
# Прибыль и EBITDA могут быть отрицательными
SignedMoney = Annotated[Decimal | None, Field(max_digits=15, decimal_places=2)]


class ApplicationAction(StrEnum):
    """Что клиент может сделать с заявкой сейчас - фронт строит по этому кнопки."""

    EDIT = "edit"
    GIVE_CONSENTS = "give_consents"
    SUBMIT = "submit"
    DECLINE_PRE_APPROVAL = "decline_pre_approval"
    UPLOAD_DOCUMENTS = "upload_documents"
    ANSWER_INFO_REQUEST = "answer_info_request"
    ACCEPT_OFFER = "accept_offer"
    REJECT_OFFER = "reject_offer"
    SIGN = "sign"


class ApplicationFinancials(BaseModel):
    annual_revenue: OptionalMoney = None
    annual_ebitda: SignedMoney = None
    annual_net_profit: SignedMoney = None
    current_debt_total: OptionalMoney = None
    monthly_debt_payments: OptionalMoney = None
    has_collateral: bool = False
    collateral_type: CollateralType | None = None
    collateral_description: str | None = None
    collateral_market_value: OptionalMoney = None


class ApplicationCreate(ApplicationFinancials):
    company_id: uuid.UUID
    product_id: uuid.UUID
    requested_amount: MoneyAmount
    requested_term_months: TermMonths
    purpose: LoanPurpose
    purpose_description: str | None = Field(default=None, max_length=2000)


class ApplicationUpdate(BaseModel):
    """Частичное обновление черновика или дополнение данных по дозапросу."""

    product_id: uuid.UUID | None = None
    requested_amount: MoneyAmount | None = None
    requested_term_months: TermMonths | None = None
    purpose: LoanPurpose | None = None
    purpose_description: str | None = Field(default=None, max_length=2000)
    annual_revenue: OptionalMoney = None
    annual_ebitda: SignedMoney = None
    annual_net_profit: SignedMoney = None
    current_debt_total: OptionalMoney = None
    monthly_debt_payments: OptionalMoney = None
    has_collateral: bool | None = None
    collateral_type: CollateralType | None = None
    collateral_description: str | None = None
    collateral_market_value: OptionalMoney = None
    version: int = Field(description="Текущая версия заявки для оптимистичной блокировки")


class ApplicationShort(ORMModel):
    id: uuid.UUID
    number: str
    company_id: uuid.UUID
    product_id: uuid.UUID
    status: ApplicationStatus
    requested_amount: Decimal
    requested_term_months: int
    created_at: datetime
    updated_at: datetime


class ApplicationRead(ApplicationShort, ApplicationFinancials):
    applicant_id: uuid.UUID
    purpose: LoanPurpose
    purpose_description: str | None
    submitted_at: datetime | None
    decided_at: datetime | None
    signed_at: datetime | None
    disbursed_at: datetime | None
    closed_at: datetime | None
    close_reason: str | None
    version: int
    status_description: str = Field(description="Понятное клиенту описание текущего этапа")
    available_actions: list[ApplicationAction]


class StatusHistoryItem(ORMModel):
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    actor_type: ActorType
    comment: str | None
    created_at: datetime


class ConsentsRequest(BaseModel):
    """Согласия на получение данных: переводит черновик в сбор данных."""

    types: list[ConsentType] = Field(min_length=1)


class ConsentRead(ORMModel):
    type: ConsentType
    granted_by_id: uuid.UUID
    created_at: datetime


class PreApprovalRecommendation(BaseModel):
    code: str = Field(examples=["add_collateral"])
    message: str = Field(examples=["Предоставьте обеспечение, чтобы увеличить сумму"])


class PreApprovalRead(ORMModel):
    approval_probability: Decimal = Field(description="0..1")
    amount_min: Decimal
    amount_max: Decimal
    estimated_rate: Decimal
    recommendations: list[PreApprovalRecommendation]
    created_at: datetime


class SignRequest(BaseModel):
    """Подписание смоделировано: код подтверждения показывается в интерфейсе, без SMS."""

    confirmation_code: str = Field(pattern=r"^\d{6}$")
