"""Компании заёмщиков."""

from datetime import date
from decimal import Decimal

from app.integrations import CompanyNotFoundError, egrul
from app.models.enums import LegalForm
from app.schemas.company import CompanyOwnerRead, CompanyRequisites
from app.services.errors import NotFoundError

REGIONS = {
    "16": "Республика Татарстан",
    "23": "Краснодарский край",
    "50": "Московская область",
    "54": "Новосибирская область",
    "66": "Свердловская область",
    "77": "Москва",
    "78": "Санкт-Петербург",
}


async def lookup_requisites(inn: str) -> CompanyRequisites:
    """Реквизиты из (мока) ЕГРЮЛ/ЕГРИП для предзаполнения."""
    try:
        data = await egrul.fetch(inn)
    except CompanyNotFoundError:
        raise NotFoundError("Компания с таким ИНН не найдена в ЕГРЮЛ/ЕГРИП") from None
    legal_form = LegalForm(data["legal_form"].lower())
    return CompanyRequisites(
        inn=data["inn"],
        ogrn=data["registration_number"],
        kpp=data.get("kpp"),
        legal_form=legal_form,
        name=data["name"],
        okved_main=data["okved_main"],
        registration_date=date.fromisoformat(data["registration_date"]),
        region=REGIONS.get(data["region_code"], f"Регион {data['region_code']}"),
        legal_address=data.get("legal_address"),
        employees_count=data["employees_count"],
        owners=[
            CompanyOwnerRead(
                full_name=f["full_name"],
                inn=f.get("inn"),
                share_percent=Decimal(str(f["share_percent"])) if "share_percent" in f else None,
                is_beneficiary=f.get("is_beneficiary", True),
            )
            for f in data.get("founders", [])
        ],
    )
