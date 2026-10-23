import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import LoanContractStatus, PaymentStatus, RepaymentType
from app.schemas.common import ORMModel


class PaymentScheduleItemRead(ORMModel):
    installment_no: int
    due_date: date
    principal_amount: Decimal
    interest_amount: Decimal
    total_amount: Decimal
    balance_after: Decimal
    status: PaymentStatus


class LoanShort(BaseModel):
    """Кредит в списке «Кредиты»: остаток и ближайший платёж считаются из графика."""

    id: uuid.UUID
    application_id: uuid.UUID
    contract_number: str
    status: LoanContractStatus
    principal_amount: Decimal
    term_months: int
    interest_rate: Decimal
    monthly_payment: Decimal
    disbursed_at: datetime | None
    maturity_date: date
    outstanding_balance: Decimal
    next_payment: PaymentScheduleItemRead | None


class LoanContractRead(LoanShort):
    """Кредитный договор с графиком платежей. До подписания - проект с плановыми датами."""

    currency: str
    repayment_type: RepaymentType
    first_payment_date: date
    signed_at: datetime | None
    signature_id: str | None
    loan_account_number: str | None
    settlement_account_number: str | None
    disbursement_transaction_id: str | None
    created_at: datetime
    schedule: list[PaymentScheduleItemRead]
