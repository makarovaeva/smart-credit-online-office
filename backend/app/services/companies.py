"""Компании заёмщиков: предзаполнение по ИНН, привязка к пользователю, профиль.

Профиль - снимок (мока) ЕГРЮЛ/ЕГРИП (реквизиты, руководитель, учредители) и данных клиента
банка из профиля заёмщика (контакты и расчётный счёт, указанные при открытии счёта).
Снимок обновляется при привязке компании и при запуске сида.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import CompanyNotFoundError, egrul, get_profile
from app.models import Company, CompanyMember, CompanyOwner, User
from app.models.enums import CompanyMemberRole, LegalForm
from app.schemas.company import (
    CompanyCreate,
    CompanyHead,
    CompanyOwnerRead,
    CompanyRead,
    CompanyRequisites,
    SettlementAccount,
)
from app.services.errors import ConflictError, NotFoundError

REGIONS = {
    "16": "Республика Татарстан",
    "23": "Краснодарский край",
    "50": "Московская область",
    "54": "Новосибирская область",
    "66": "Свердловская область",
    "77": "Москва",
    "78": "Санкт-Петербург",
}


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


async def lookup_requisites(inn: str) -> CompanyRequisites:
    """Реквизиты, руководитель и учредители из (мока) ЕГРЮЛ/ЕГРИП для предзаполнения."""
    try:
        data = await egrul.fetch(inn)
    except CompanyNotFoundError:
        raise NotFoundError("Компания с таким ИНН не найдена в ЕГРЮЛ/ЕГРИП") from None
    company = data["company"]
    head = data.get("head")
    return CompanyRequisites(
        inn=company["inn"],
        ogrn=company["ogrn"],
        kpp=company.get("kpp"),
        legal_form=LegalForm(company["legal_form"].lower()),
        name=company["short_name"],
        full_name=company.get("full_name"),
        okved_main=company["okved_main"]["code"],
        okved_name=company["okved_main"].get("name"),
        tax_system=company.get("tax_system"),
        registration_date=date.fromisoformat(company["registration_date"]),
        region=REGIONS.get(company["region_code"], f"Регион {company['region_code']}"),
        legal_address=company.get("legal_address"),
        employees_count=company["employees_count"],
        head=(
            CompanyHead(
                full_name=head["full_name"],
                position=head.get("position"),
                in_position_since=_date(head.get("in_position_since")),
                has_signing_authority=head.get("has_signing_authority", True),
            )
            if head
            else None
        ),
        owners=[
            CompanyOwnerRead(
                full_name=owner["name"],
                inn=owner.get("inn"),
                share_percent=owner.get("ownership_share_pct"),
                is_beneficiary=owner.get("is_beneficiary", True),
                has_signing_authority=owner.get("has_signing_authority", False),
            )
            for owner in data.get("owners") or []
        ],
    )


def _client_data(inn: str) -> dict[str, Any]:
    """Контакты и расчётный счёт из профиля клиента банка."""
    try:
        profile = get_profile(inn)
    except CompanyNotFoundError:
        return {}
    contacts, account = profile.contacts or {}, profile.bank_account or {}
    return {
        "phone": contacts.get("phone"),
        "email": contacts.get("email"),
        "settlement_account_number": account.get("account_number"),
        "settlement_bik": account.get("bik"),
        "settlement_bank_name": account.get("bank_name"),
    }


async def sync_company(session: AsyncSession, inn: str) -> Company:
    """Создаёт компанию или обновляет снимок реестра и данных клиента. Коммит - на вызывающем.
    Заполненные клиентом фактический адрес и число сотрудников не затираются."""
    requisites = await lookup_requisites(inn)
    head = requisites.head
    values: dict[str, Any] = {
        "ogrn": requisites.ogrn,
        "kpp": requisites.kpp,
        "legal_form": requisites.legal_form,
        "name": requisites.name,
        "full_name": requisites.full_name,
        "okved_main": requisites.okved_main,
        "okved_name": requisites.okved_name,
        "tax_system": requisites.tax_system,
        "registration_date": requisites.registration_date,
        "region": requisites.region,
        "legal_address": requisites.legal_address or requisites.region,
        "head_full_name": head.full_name if head else None,
        "head_position": head.position if head else None,
        "head_in_position_since": head.in_position_since if head else None,
        "head_has_signing_authority": head.has_signing_authority if head else False,
    } | _client_data(inn)

    company = await session.scalar(select(Company).where(Company.inn == inn))
    if company is None:
        company = Company(inn=inn, employees_count=requisites.employees_count, **values)
        session.add(company)
        await session.flush()
    else:
        for key, value in values.items():
            setattr(company, key, value)
        if company.employees_count is None:
            company.employees_count = requisites.employees_count
        await session.execute(delete(CompanyOwner).where(CompanyOwner.company_id == company.id))
    session.add_all(
        CompanyOwner(company_id=company.id, **owner.model_dump()) for owner in requisites.owners
    )
    await session.flush()
    return company


async def link_company(session: AsyncSession, user: User, body: CompanyCreate) -> CompanyRead:
    """Привязать компанию к пользователю. Реквизиты - из реестра, а не из запроса.

    Компания, уже привязанная к клиенту банка, повторно не привязывается: добавление
    представителей требует подтверждения полномочий, в прототипе его нет (409)."""
    existing = await session.scalar(select(Company).where(Company.inn == body.inn))
    if existing is not None:
        if await _membership(session, user, existing.id) is not None:
            raise ConflictError("Компания уже привязана к вашему профилю")
        raise ConflictError("Компания уже обслуживается в банке: обратитесь к её владельцу")
    company = await sync_company(session, body.inn)
    if body.actual_address is not None:
        company.actual_address = body.actual_address
    if body.employees_count is not None:
        company.employees_count = body.employees_count
    session.add(CompanyMember(company_id=company.id, user_id=user.id, role=body.member_role))
    await session.commit()
    return await to_read(session, company, body.member_role)


async def _membership(
    session: AsyncSession, user: User, company_id: uuid.UUID
) -> CompanyMemberRole | None:
    return await session.scalar(
        select(CompanyMember.role).where(
            CompanyMember.company_id == company_id, CompanyMember.user_id == user.id
        )
    )


async def list_companies(session: AsyncSession, user: User) -> list[CompanyRead]:
    rows = await session.execute(
        select(Company, CompanyMember.role)
        .join(CompanyMember, CompanyMember.company_id == Company.id)
        .where(CompanyMember.user_id == user.id)
        .order_by(Company.name)
    )
    return [await to_read(session, company, role) for company, role in rows]


async def get_company(session: AsyncSession, user: User, company_id: uuid.UUID) -> CompanyRead:
    """Профиль компании, в которой состоит пользователь. Чужая - 404."""
    role = await _membership(session, user, company_id)
    company = await session.get(Company, company_id) if role is not None else None
    if company is None:
        raise NotFoundError("Компания не найдена")
    return await to_read(session, company, role)


async def to_read(
    session: AsyncSession, company: Company, member_role: CompanyMemberRole | None = None
) -> CompanyRead:
    owners = [
        CompanyOwnerRead.model_validate(o)
        for o in await session.scalars(
            select(CompanyOwner)
            .where(CompanyOwner.company_id == company.id)
            .order_by(CompanyOwner.share_percent.desc().nulls_last(), CompanyOwner.full_name)
        )
    ]
    head = (
        CompanyHead(
            full_name=company.head_full_name,
            position=company.head_position,
            in_position_since=company.head_in_position_since,
            has_signing_authority=company.head_has_signing_authority,
        )
        if company.head_full_name
        else None
    )
    signatories = [head.full_name] if head and head.has_signing_authority else []
    signatories += [
        o.full_name for o in owners if o.has_signing_authority and o.full_name not in signatories
    ]
    return CompanyRead(
        id=company.id,
        inn=company.inn,
        ogrn=company.ogrn,
        kpp=company.kpp,
        legal_form=company.legal_form,
        name=company.name,
        full_name=company.full_name,
        okved_main=company.okved_main,
        okved_name=company.okved_name,
        tax_system=company.tax_system,
        registration_date=company.registration_date,
        region=company.region,
        legal_address=company.legal_address,
        actual_address=company.actual_address,
        employees_count=company.employees_count,
        head=head,
        owners=owners,
        phone=company.phone,
        email=company.email,
        settlement_account=(
            SettlementAccount(
                account_number=company.settlement_account_number,
                bik=company.settlement_bik,
                bank_name=company.settlement_bank_name,
            )
            if company.settlement_account_number
            else None
        ),
        signatories=signatories,
        member_role=member_role,
    )
