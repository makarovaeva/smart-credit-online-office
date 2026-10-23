import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, Sequence, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    ActorType,
    ApplicationStatus,
    CloseReason,
    CollateralType,
    ConsentType,
    LoanPurpose,
)
from app.models.mixins import CreatedAtMixin, Money, TimestampMixin, UUIDPkMixin, str_enum

# Источник человекочитаемого номера заявки (CR-2026-000123)
application_number_seq = Sequence("application_number_seq", metadata=Base.metadata)


class Application(UUIDPkMixin, TimestampMixin, Base):
    """Кредитная заявка - центральный объект конвейера."""

    __tablename__ = "applications"

    number: Mapped[str] = mapped_column(String(32), unique=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    applicant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("credit_products.id"))
    status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus), default=ApplicationStatus.DRAFT, index=True
    )
    # Текущий ответственный сотрудник: аналитик на эскалации или андеррайтер на рассмотрении
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)

    # Параметры запроса
    requested_amount: Mapped[Decimal] = mapped_column(Money)
    requested_term_months: Mapped[int]
    purpose: Mapped[LoanPurpose] = mapped_column(str_enum(LoanPurpose))
    purpose_description: Mapped[str | None] = mapped_column(Text)

    # Финансовые показатели со слов клиента, nullable: заполняются по ходу черновика.
    # ИИ сверяет их с отчётностью и внешними источниками.
    annual_revenue: Mapped[Decimal | None] = mapped_column(Money)
    annual_ebitda: Mapped[Decimal | None] = mapped_column(Money)
    annual_net_profit: Mapped[Decimal | None] = mapped_column(Money)
    # Действующие обязательства: кредиты, лизинг, аренда
    current_debt_total: Mapped[Decimal | None] = mapped_column(Money)
    monthly_debt_payments: Mapped[Decimal | None] = mapped_column(Money)
    has_collateral: Mapped[bool] = mapped_column(default=False)
    collateral_type: Mapped[CollateralType | None] = mapped_column(str_enum(CollateralType))
    collateral_description: Mapped[str | None] = mapped_column(Text)
    collateral_address: Mapped[str | None] = mapped_column(Text)
    collateral_market_value: Mapped[Decimal | None] = mapped_column(Money)
    # Обременения со слов клиента: залог у другого банка, арест и т.п.
    collateral_encumbrances: Mapped[str | None] = mapped_column(Text)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[CloseReason | None] = mapped_column(str_enum(CloseReason))

    # Оптимистичная блокировка: клиент и сотрудники банка не перетрут изменения друг друга
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": version}


class ApplicationConsent(UUIDPkMixin, CreatedAtMixin, Base):
    """Согласия клиента на получение данных - без них ИИ не начинает сбор данных."""

    __tablename__ = "application_consents"
    __table_args__ = (UniqueConstraint("application_id", "type"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    type: Mapped[ConsentType] = mapped_column(str_enum(ConsentType))
    granted_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PreApproval(UUIDPkMixin, CreatedAtMixin, Base):
    """Предварительный лимит: клиент видит шансы и диапазон до подачи заявки."""

    __tablename__ = "pre_approvals"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    approval_probability: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    amount_min: Mapped[Decimal] = mapped_column(Money)
    amount_max: Mapped[Decimal] = mapped_column(Money)
    estimated_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    collateral_required: Mapped[bool] = mapped_column(default=False)
    # [{"code": "...", "message": "Предоставьте обеспечение, чтобы увеличить сумму"}]
    recommendations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class ApplicationStatusHistory(UUIDPkMixin, CreatedAtMixin, Base):
    """Аудит переходов статуса: таймлайн для клиента и журнал для банка."""

    __tablename__ = "application_status_history"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        str_enum(ApplicationStatus, name="from_status")
    )
    to_status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus, name="to_status")
    )
    actor_type: Mapped[ActorType] = mapped_column(str_enum(ActorType))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)
