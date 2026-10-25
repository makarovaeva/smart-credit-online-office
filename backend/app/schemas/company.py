import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from app.models.enums import CompanyMemberRole, LegalForm
from app.schemas.common import ORMModel

Inn = Annotated[str, Field(pattern=r"^(\d{10}|\d{12})$", examples=["7712345678"])]


class CompanyOwnerRead(ORMModel):
    full_name: str
    inn: str | None
    share_percent: Decimal | None
    is_beneficiary: bool
    has_signing_authority: bool = False


class CompanyHead(BaseModel):
    full_name: str
    position: str | None
    in_position_since: date | None
    has_signing_authority: bool


class CompanyRequisites(BaseModel):
    """Реквизиты из (мока) ЕГРЮЛ/ЕГРИП: клиенту не нужно вводить их вручную."""

    inn: str
    ogrn: str
    kpp: str | None
    legal_form: LegalForm
    name: str
    full_name: str | None = None
    okved_main: str
    okved_name: str | None = None
    # usn_income / usn_income_expense / osno / ...
    tax_system: str | None = None
    registration_date: date
    region: str
    # В формате данных ML адреса и учредителей нет - приходят, только если генератор их отдаёт
    legal_address: str | None
    employees_count: int | None = None
    head: CompanyHead | None = None
    owners: list[CompanyOwnerRead] = Field(description="Учредители и бенефициары из реестра")


class CompanyCreate(BaseModel):
    inn: Inn
    member_role: CompanyMemberRole
    actual_address: str | None = Field(default=None, max_length=500)
    employees_count: int | None = Field(default=None, ge=0)


class SettlementAccount(BaseModel):
    account_number: str
    bik: str | None
    bank_name: str | None


class CompanyRead(CompanyRequisites, ORMModel):
    """Профиль компании: реквизиты и владельцы из реестра, контакты и счёт - данные клиента
    банка (указаны при открытии счёта)."""

    id: uuid.UUID
    actual_address: str | None
    phone: str | None = None
    email: str | None = None
    settlement_account: SettlementAccount | None = None
    signatories: list[str] = Field(
        default=[], description="Кто вправе подписывать документы: руководитель и учредители"
    )
    member_role: CompanyMemberRole | None = Field(
        default=None, description="Роль текущего пользователя в компании (для клиента)"
    )
