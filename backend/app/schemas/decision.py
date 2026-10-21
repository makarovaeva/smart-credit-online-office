import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    AiRecommendation,
    CheckSource,
    CheckStatus,
    DecisionType,
    OfferResponse,
    RiskGrade,
    RiskZone,
)
from app.schemas.common import MoneyAmount, ORMModel, TermMonths
from app.schemas.document import InfoRequestCreate


class DecisionReason(BaseModel):
    code: str = Field(examples=["high_debt_burden"])
    message: str = Field(examples=["Для одобрения требуется снизить долговую нагрузку"])


class OfferCondition(BaseModel):
    code: str = Field(examples=["owner_surety"])
    description: str = Field(examples=["Поручительство собственника бизнеса"])


class OfferRead(ORMModel):
    """Оффер глазами клиента: без скорингового балла и внутренних факторов."""

    id: uuid.UUID
    decision_type: DecisionType
    approved_amount: Decimal | None
    approved_term_months: int | None
    interest_rate: Decimal | None
    estimated_monthly_payment: Decimal | None
    conditions: list[OfferCondition]
    reasons: list[DecisionReason]
    valid_until: datetime | None
    client_response: OfferResponse | None
    created_at: datetime


class RejectOfferRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ExternalCheckRead(ORMModel):
    id: uuid.UUID
    source: CheckSource
    status: CheckStatus
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class ScoringFactor(BaseModel):
    code: str = Field(examples=["dscr"])
    value: Any
    impact: int = Field(description="Вклад в балл: + снижает риск, - повышает")
    description: str


class StopFactor(BaseModel):
    code: str = Field(examples=["account_blocked_115fz"])
    category: str = Field(examples=["legal"], description="legal | financial | fictitious | fraud")
    description: str


class EscalationReason(BaseModel):
    code: str = Field(examples=["low_confidence"])
    description: str = Field(examples=["Уверенность модели ниже 80%"])


class ScoringResultRead(ORMModel):
    id: uuid.UUID
    model_version: str
    dscr: Decimal | None
    debt_burden: Decimal | None
    ltv: Decimal | None
    metrics: dict[str, Any]
    score: int
    risk_grade: RiskGrade
    risk_zone: RiskZone
    confidence: Decimal
    fraud_score: Decimal | None
    factors: list[ScoringFactor]
    stop_factors: list[StopFactor]
    escalation_reasons: list[EscalationReason]
    created_at: datetime


class CreditMemoRead(ORMModel):
    id: uuid.UUID
    scoring_result_id: uuid.UUID
    summary: str
    ai_recommendation: AiRecommendation
    recommended_amount: Decimal | None
    recommended_term_months: int | None
    recommended_rate: Decimal | None
    recommended_conditions: list[OfferCondition]
    analyst_id: uuid.UUID | None
    analyst_conclusion: str | None
    analyst_completed_at: datetime | None
    created_at: datetime


class AnalystConclusionRequest(BaseModel):
    """Аналитик подтверждает или корректирует вывод ИИ; заявка уходит андеррайтеру."""

    conclusion: str = Field(min_length=1, max_length=5000)
    recommendation: AiRecommendation
    recommended_amount: MoneyAmount | None = None
    recommended_term_months: TermMonths | None = None
    recommended_rate: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    recommended_conditions: list[OfferCondition] = []


class DecisionRead(OfferRead):
    """Полное решение для банка."""

    credit_memo_id: uuid.UUID
    decided_by_id: uuid.UUID
    comment: str | None
    client_responded_at: datetime | None


class UnderwriterDecisionRequest(BaseModel):
    """approved/conditional_approval требуют условий оффера,
    more_information_required - дозапроса клиенту."""

    decision_type: DecisionType
    approved_amount: MoneyAmount | None = None
    approved_term_months: TermMonths | None = None
    interest_rate: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    conditions: list[OfferCondition] = []
    reasons: list[DecisionReason] = []
    info_request: InfoRequestCreate | None = None
    comment: str | None = Field(default=None, max_length=2000)
