"""Компании заёмщиков."""

from datetime import date
from decimal import Decimal

from app.integrations import CompanyNotFoundError, egrul
from app.schemas.company import CompanyOwnerRead, CompanyRequisites
from app.services.errors import NotFoundError


async def lookup_requisites(inn: str) -> CompanyRequisites:
    """Реквизиты и учредители из (мока) ЕГРЮЛ/ЕГРИП для предзаполнения."""
    try:
        data = await egrul.fetch(inn)
    except CompanyNotFoundError:
        raise NotFoundError("Компания с таким ИНН не найдена в ЕГРЮЛ/ЕГРИП") from None
    return CompanyRequisites(
        inn=data["inn"],
        ogrn=data["ogrn"],
        kpp=data["kpp"],
        legal_form=data["legal_form"],
        name=data["name"],
        okved_main=data["okved_main"]["code"],
        registration_date=date.fromisoformat(data["registration_date"]),
        region=data["region"],
        legal_address=data["legal_address"],
        owners=[
            CompanyOwnerRead(
                full_name=f["full_name"],
                inn=f["inn"],
                share_percent=Decimal(f["share_percent"]),
                is_beneficiary=f["is_beneficiary"],
            )
            for f in data["founders"]
        ],
    )
