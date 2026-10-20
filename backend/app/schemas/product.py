import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import CreditFormat, LoanPurpose
from app.schemas.common import MoneyAmount, ORMModel, TermMonths


class ProductRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    credit_format: CreditFormat
    purposes: list[LoanPurpose]
    min_amount: Decimal
    max_amount: Decimal
    min_term_months: int
    max_term_months: int
    base_rate: Decimal
    requires_collateral: bool


class ProductMatchRequest(BaseModel):
    """Подбор продукта для клиента без банковской экспертизы: цель + сумма + срок."""

    purpose: LoanPurpose
    amount: MoneyAmount
    term_months: TermMonths
    credit_format: CreditFormat | None = None
    has_collateral: bool = False


class ProductMatch(BaseModel):
    product: ProductRead
    fits: bool
    # Пояснения на человеческом языке: почему подходит или что изменить
    notes: list[str]
    estimated_rate: Decimal
    estimated_monthly_payment: Decimal
