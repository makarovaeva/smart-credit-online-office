import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import CompanyMemberRole, LegalForm
from app.models.mixins import TimestampMixin, UUIDPkMixin, str_enum


class Company(UUIDPkMixin, TimestampMixin, Base):
    """Заёмщик: ИП или юрлицо. Реквизиты, руководитель и учредители - снимок (мока) ЕГРЮЛ/ЕГРИП
    по ИНН, контакты и расчётный счёт - данные клиента банка (services/companies.py)."""

    __tablename__ = "companies"

    inn: Mapped[str] = mapped_column(String(12), unique=True)
    ogrn: Mapped[str] = mapped_column(String(15))
    kpp: Mapped[str | None] = mapped_column(String(9))
    legal_form: Mapped[LegalForm] = mapped_column(str_enum(LegalForm))
    name: Mapped[str] = mapped_column(String(500))
    full_name: Mapped[str | None] = mapped_column(String(1000))
    okved_main: Mapped[str] = mapped_column(String(10))
    okved_name: Mapped[str | None] = mapped_column(String(500))
    # usn_income / usn_income_expense / osno / ... - справочник открыт (формат Borrower Profile)
    tax_system: Mapped[str | None] = mapped_column(String(32))
    registration_date: Mapped[date]
    region: Mapped[str] = mapped_column(String(100))
    legal_address: Mapped[str] = mapped_column(String(500))
    actual_address: Mapped[str | None] = mapped_column(String(500))
    employees_count: Mapped[int | None]
    head_full_name: Mapped[str | None] = mapped_column(String(255))
    head_position: Mapped[str | None] = mapped_column(String(255))
    head_in_position_since: Mapped[date | None]
    head_has_signing_authority: Mapped[bool] = mapped_column(default=True, server_default="true")
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    # Расчётный счёт в банке - на него зачисляется кредит
    settlement_account_number: Mapped[str | None] = mapped_column(String(20))
    settlement_bik: Mapped[str | None] = mapped_column(String(9))
    settlement_bank_name: Mapped[str | None] = mapped_column(String(255))


class CompanyMember(UUIDPkMixin, TimestampMixin, Base):
    """Связь пользователя с компанией: от имени одной компании могут действовать несколько людей."""

    __tablename__ = "company_members"
    __table_args__ = (UniqueConstraint("company_id", "user_id"),)

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[CompanyMemberRole] = mapped_column(str_enum(CompanyMemberRole))


class CompanyOwner(UUIDPkMixin, TimestampMixin, Base):
    """Учредитель/бенефициар: проверка санкций и сложной структуры владения."""

    __tablename__ = "company_owners"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(255))
    # ИНН физлица или юрлица-учредителя
    inn: Mapped[str | None] = mapped_column(String(12))
    share_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    is_beneficiary: Mapped[bool] = mapped_column(default=False)
    has_signing_authority: Mapped[bool] = mapped_column(default=False, server_default="false")
