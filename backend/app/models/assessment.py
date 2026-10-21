import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    AiRecommendation,
    CheckSource,
    CheckStatus,
    DecisionType,
    MoreInfoTarget,
    OfferResponse,
    RiskGrade,
    RiskZone,
)
from app.models.mixins import CreatedAtMixin, Money, UUIDPkMixin, str_enum

Ratio = Numeric(8, 4)


class ExternalCheck(UUIDPkMixin, CreatedAtMixin, Base):
    """Обращение к внешнему источнику (моки ЕГРЮЛ, ФНС, БКИ, ФССП...) и его сырой ответ."""

    __tablename__ = "external_checks"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[CheckSource] = mapped_column(str_enum(CheckSource))
    status: Mapped[CheckStatus] = mapped_column(str_enum(CheckStatus), default=CheckStatus.PENDING)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScoringResult(UUIDPkMixin, CreatedAtMixin, Base):
    """Финансовый анализ и скоринг. Это вход для маршрутизации, а не кредитное решение."""

    __tablename__ = "scoring_results"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    model_version: Mapped[str] = mapped_column(String(50))

    # Метрики финансового анализа
    dscr: Mapped[Decimal | None] = mapped_column(Ratio)
    debt_burden: Mapped[Decimal | None] = mapped_column(Ratio)
    ltv: Mapped[Decimal | None] = mapped_column(Ratio)
    # Прочие показатели: EBITDA, cash flow по месяцам, сезонность, концентрация клиентов
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    score: Mapped[int]
    risk_grade: Mapped[RiskGrade] = mapped_column(str_enum(RiskGrade))
    risk_zone: Mapped[RiskZone] = mapped_column(str_enum(RiskZone))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    fraud_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    # [{"code": "dscr", "value": 0.9, "impact": -35, "description": "..."}] - объяснимость
    factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{"code": "accounts_blocked_115fz", "category": "legal", "description": "..."}]
    # Любой стоп-фактор - красная зона и автоотказ
    stop_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Основания эскалации аналитику: confidence<80%, бизнес младше года, LTV>=70% и т.д.
    escalation_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class CreditMemo(UUIDPkMixin, CreatedAtMixin, Base):
    """AI Credit Memo: заключение ИИ + выводы аналитика. Рассматривается андеррайтером."""

    __tablename__ = "credit_memos"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    scoring_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scoring_results.id"))
    summary: Mapped[str] = mapped_column(Text)
    ai_recommendation: Mapped[AiRecommendation] = mapped_column(str_enum(AiRecommendation))
    recommended_amount: Mapped[Decimal | None] = mapped_column(Money)
    recommended_term_months: Mapped[int | None]
    recommended_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # Доп. условия рекомендации: залог, гарантия Корпорации МСП, поручительство собственника
    recommended_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Чем контр-предложение отличается от запроса:
    # [{"scenario": "term_extension", "field": "term_months", "old_value": 24, "new_value": 36}]
    counter_offer_adjustments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Заполняется на этапе analyst_escalation
    analyst_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    analyst_conclusion: Mapped[str | None] = mapped_column(Text)
    analyst_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditDecision(UUIDPkMixin, CreatedAtMixin, Base):
    """Решение андеррайтера и, для одобрения, оффер с реакцией клиента."""

    __tablename__ = "credit_decisions"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    credit_memo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("credit_memos.id"))
    decision_type: Mapped[DecisionType] = mapped_column(str_enum(DecisionType))
    decided_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    # Для more_information_required: документы у клиента или экспертиза аналитика
    more_info_target: Mapped[MoreInfoTarget | None] = mapped_column(str_enum(MoreInfoTarget))
    # Причины решения, понятные клиенту
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Условия оффера; заполнены для approved и conditional_approval
    approved_amount: Mapped[Decimal | None] = mapped_column(Money)
    approved_term_months: Mapped[int | None]
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_response: Mapped[OfferResponse | None] = mapped_column(str_enum(OfferResponse))
    client_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
