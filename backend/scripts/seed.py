"""Демо-данные: сотрудники банка, клиенты с компаниями на демо-ИНН и кредитные продукты.

Идемпотентно: существующие записи обновляются, запускать можно при каждом старте.
    uv run python -m scripts.seed
"""

import asyncio
import secrets
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import SessionFactory
from app.models import Company, CompanyMember, CompanyOwner, CreditProduct, User
from app.models.enums import CompanyMemberRole, CreditFormat, LoanPurpose, UserRole
from app.services.companies import lookup_requisites

# Общий пароль демо-сотрудников - в README
EMPLOYEE_PASSWORD = "demo-password"

EMPLOYEES = [
    ("analyst1@alfa-demo.ru", "Анна Кредитова", UserRole.CREDIT_ANALYST),
    ("analyst2@alfa-demo.ru", "Борис Рискин", UserRole.CREDIT_ANALYST),
    ("underwriter1@alfa-demo.ru", "Виктор Решетов", UserRole.UNDERWRITER),
    ("underwriter2@alfa-demo.ru", "Галина Лимитова", UserRole.UNDERWRITER),
    ("admin@alfa-demo.ru", "Администратор", UserRole.ADMIN),
]

# Телефон, имя, ИНН компании (демо-сценарии из app/integrations/synthetic.py)
CLIENTS = [
    ("+79990000001", "Алексей Иванов", "7701000001"),  # здоровая компания
    ("+79990000002", "Сергей Смирнов", "7712345678"),  # пограничный риск: 5 млн - контр-оффер
    ("+79990000003", "Дмитрий Кузнецов", "7701000002"),  # недействующая компания: автоотказ
    ("+79990000004", "Андрей Попов", "7701000007"),  # бизнесу 7 месяцев: к аналитику
    ("+79990000005", "Михаил Соколов", "770100000001"),  # ИП
]

PRODUCTS = [
    {
        "code": "working-capital",
        "name": "Оборотный кредит",
        "description": "Пополнение оборотных средств: закупка товара, сырья, сезонные расходы",
        "credit_format": CreditFormat.LOAN,
        "purposes": [
            LoanPurpose.WORKING_CAPITAL,
            LoanPurpose.BUSINESS_EXPANSION,
            LoanPurpose.OTHER,
        ],
        "min_amount": Decimal("300000"),
        "max_amount": Decimal("10000000"),
        "min_term_months": 6,
        "max_term_months": 60,
        "base_rate": Decimal("18.00"),
    },
    {
        "code": "equipment",
        "name": "Кредит на оборудование",
        "description": "Покупка оборудования и транспорта для бизнеса",
        "credit_format": CreditFormat.LOAN,
        "purposes": [LoanPurpose.EQUIPMENT, LoanPurpose.BUSINESS_EXPANSION],
        "min_amount": Decimal("500000"),
        "max_amount": Decimal("20000000"),
        "min_term_months": 12,
        "max_term_months": 84,
        "base_rate": Decimal("16.50"),
    },
    {
        "code": "refinancing",
        "name": "Рефинансирование",
        "description": "Перевод кредитов из других банков на более выгодные условия",
        "credit_format": CreditFormat.LOAN,
        "purposes": [LoanPurpose.REFINANCING],
        "min_amount": Decimal("1000000"),
        "max_amount": Decimal("15000000"),
        "min_term_months": 12,
        "max_term_months": 60,
        "base_rate": Decimal("17.00"),
    },
    {
        "code": "overdraft",
        "name": "Овердрафт",
        "description": "Кредитный лимит на расчётном счёте для кассовых разрывов",
        "credit_format": CreditFormat.OVERDRAFT,
        "purposes": [LoanPurpose.WORKING_CAPITAL],
        "min_amount": Decimal("100000"),
        "max_amount": Decimal("3000000"),
        "min_term_months": 1,
        "max_term_months": 12,
        "base_rate": Decimal("20.00"),
    },
]


async def _upsert(session: AsyncSession, model, key: str, values: dict):
    obj = await session.scalar(select(model).where(getattr(model, key) == values[key]))
    if obj is None:
        obj = model(**values)
        session.add(obj)
    else:
        for field, value in values.items():
            setattr(obj, field, value)
    await session.flush()
    return obj


async def _company(session: AsyncSession, inn: str, owner: User) -> None:
    requisites = await lookup_requisites(inn)
    company = await _upsert(
        session,
        Company,
        "inn",
        {
            "inn": inn,
            "ogrn": requisites.ogrn,
            "kpp": requisites.kpp,
            "legal_form": requisites.legal_form,
            "name": requisites.name,
            "okved_main": requisites.okved_main,
            "registration_date": requisites.registration_date,
            "region": requisites.region,
            # В формате данных ML адреса нет
            "legal_address": requisites.legal_address or requisites.region,
            "employees_count": requisites.employees_count,
        },
    )
    member = await session.scalar(
        select(CompanyMember).where(
            CompanyMember.company_id == company.id, CompanyMember.user_id == owner.id
        )
    )
    if member is None:
        session.add(
            CompanyMember(company_id=company.id, user_id=owner.id, role=CompanyMemberRole.OWNER)
        )
    has_owners = await session.scalar(
        select(CompanyOwner.id).where(CompanyOwner.company_id == company.id).limit(1)
    )
    if not has_owners:
        session.add(
            CompanyOwner(
                company_id=company.id,
                full_name=owner.full_name,
                share_percent=Decimal("100"),
                is_beneficiary=True,
            )
        )


async def seed(session: AsyncSession) -> None:
    employee_hash = hash_password(EMPLOYEE_PASSWORD)
    for email, full_name, role in EMPLOYEES:
        await _upsert(
            session,
            User,
            "email",
            {"email": email, "full_name": full_name, "role": role, "password_hash": employee_hash},
        )
    for phone, full_name, inn in CLIENTS:
        client = await session.scalar(select(User).where(User.phone == phone))
        if client is None:
            client = User(
                email=f"client{phone[-2:]}@example.com",
                phone=phone,
                full_name=full_name,
                role=UserRole.CLIENT,
                # Клиенты входят по телефону, пароль не используется
                password_hash=hash_password(secrets.token_urlsafe(16)),
            )
            session.add(client)
            await session.flush()
        await _company(session, inn, client)
    for product in PRODUCTS:
        await _upsert(session, CreditProduct, "code", product)
    await session.commit()


async def main() -> None:
    async with SessionFactory() as session:
        await seed(session)
    print(
        f"Демо-данные готовы: {len(EMPLOYEES)} сотрудников, {len(CLIENTS)} клиентов, "
        f"{len(PRODUCTS)} продуктов"
    )


if __name__ == "__main__":
    asyncio.run(main())
