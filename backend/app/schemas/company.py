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


class CompanyRequisites(BaseModel):
    """Реквизиты из (мока) ЕГРЮЛ/ЕГРИП: клиенту не нужно вводить их вручную."""

    inn: str
    ogrn: str
    kpp: str | None
    legal_form: LegalForm
    name: str
    okved_main: str
    registration_date: date
    region: str
    # В формате данных ML адреса и учредителей нет - приходят, только если генератор их отдаёт
    legal_address: str | None
    employees_count: int | None = None
    owners: list[CompanyOwnerRead] = Field(description="Учредители и бенефициары из реестра")


class CompanyCreate(BaseModel):
    inn: Inn
    member_role: CompanyMemberRole
    actual_address: str | None = Field(default=None, max_length=500)
    employees_count: int | None = Field(default=None, ge=0)


class CompanyRead(CompanyRequisites, ORMModel):
    id: uuid.UUID
    actual_address: str | None
