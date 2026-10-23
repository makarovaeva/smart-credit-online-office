import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, Sequence, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import LoanContractStatus, PaymentStatus, RepaymentType
from app.models.mixins import CreatedAtMixin, Money, TimestampMixin, UUIDPkMixin, str_enum

# Источник номера договора (КД-2026-000045) и ссудного счёта
contract_number_seq = Sequence("contract_number_seq", metadata=Base.metadata)


class LoanContract(UUIDPkMixin, TimestampMixin, Base):
    """Кредитный договор, после выдачи - действующий кредит. Условия - неизменяемый снимок
    принятого оффера. Подписание и выдача смоделированы."""

    __tablename__ = "loan_contracts"

    # Одна заявка - один договор: повторная подготовка не создаёт дубль
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), unique=True
    )
    # Принятый оффер (решение андеррайтера)
    credit_decision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_decisions.id"), unique=True
    )
    contract_number: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[LoanContractStatus] = mapped_column(
        str_enum(LoanContractStatus), default=LoanContractStatus.AWAITING_SIGNATURE
    )

    principal_amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    term_months: Mapped[int]
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    repayment_type: Mapped[RepaymentType] = mapped_column(
        str_enum(RepaymentType), default=RepaymentType.ANNUITY
    )
    monthly_payment: Mapped[Decimal] = mapped_column(Money)
    first_payment_date: Mapped[date]
    maturity_date: Mapped[date]

    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signature_id: Mapped[str | None] = mapped_column(String(64))

    # Ссудный счёт открывается при выдаче
    loan_account_number: Mapped[str | None] = mapped_column(String(20), unique=True)
    # Расчётный счёт клиента, куда зачислены средства
    settlement_account_number: Mapped[str | None] = mapped_column(String(20))
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disbursement_transaction_id: Mapped[str | None] = mapped_column(String(64))


class PaymentScheduleItem(UUIDPkMixin, CreatedAtMixin, Base):
    """Строка графика платежей. Остаток долга и ближайший платёж считаются из графика."""

    __tablename__ = "payment_schedule_items"
    __table_args__ = (UniqueConstraint("contract_id", "installment_no"),)

    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("loan_contracts.id", ondelete="CASCADE"), index=True
    )
    installment_no: Mapped[int]
    due_date: Mapped[date]
    principal_amount: Mapped[Decimal] = mapped_column(Money)
    interest_amount: Mapped[Decimal] = mapped_column(Money)
    total_amount: Mapped[Decimal] = mapped_column(Money)
    balance_after: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[PaymentStatus] = mapped_column(
        str_enum(PaymentStatus), default=PaymentStatus.SCHEDULED
    )
