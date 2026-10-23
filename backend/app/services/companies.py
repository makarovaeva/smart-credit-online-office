"""Компании заёмщиков."""

from datetime import date

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
    """Реквизиты и учредители из (мока) ЕГРЮЛ/ЕГРИП для предзаполнения."""
    try:
        data = await egrul.fetch(inn)
    except CompanyNotFoundError:
        raise NotFoundError("Компания с таким ИНН не найдена в ЕГРЮЛ/ЕГРИП") from None
    company = data["company"]
    return CompanyRequisites(
        inn=company["inn"],
        ogrn=company["ogrn"],
        kpp=company.get("kpp"),
        legal_form=LegalForm(company["legal_form"].lower()),
        name=company["short_name"],
        okved_main=company["okved_main"]["code"],
        registration_date=date.fromisoformat(company["registration_date"]),
        region=REGIONS.get(company["region_code"], f"Регион {company['region_code']}"),
        legal_address=company.get("legal_address"),
        employees_count=company["employees_count"],
        owners=[
            CompanyOwnerRead(
                full_name=owner["name"],
                inn=owner.get("inn"),
                share_percent=owner.get("ownership_share_pct"),
                is_beneficiary=owner.get("is_beneficiary", True),
            )
            for owner in data.get("owners") or []
        ],
    )
