from decimal import Decimal

from sqlalchemy import ARRAY, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import CreditFormat, LoanPurpose
from app.models.mixins import Money, TimestampMixin, UUIDPkMixin, str_enum


class CreditProduct(UUIDPkMixin, TimestampMixin, Base):
    """Кредитный продукт каталога с параметрами, на которые опирается кредитная логика."""

    __tablename__ = "credit_products"

    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    credit_format: Mapped[CreditFormat] = mapped_column(str_enum(CreditFormat))
    purposes: Mapped[list[LoanPurpose]] = mapped_column(ARRAY(str_enum(LoanPurpose, check=False)))
    min_amount: Mapped[Decimal] = mapped_column(Money)
    max_amount: Mapped[Decimal] = mapped_column(Money)
    min_term_months: Mapped[int]
    max_term_months: Mapped[int]
    base_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    requires_collateral: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
