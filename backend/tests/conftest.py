"""Фикстуры для тестов API с Postgres.

Нужна отдельная БД: TEST_DATABASE_URL=postgresql+asyncpg://... Без неё тесты с БД пропускаются.
Схема накатывается миграциями один раз, каждый тест работает в транзакции и откатывается.
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.main import app
from app.models import Company, CompanyMember, CreditProduct, User
from app.models.enums import CompanyMemberRole, CreditFormat, LegalForm, LoanPurpose, UserRole

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "password"
# PBKDF2 намеренно медленный - считаем хеш один раз на прогон
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture(scope="session")
def migrated_db() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL не задан")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=os.environ | {"DATABASE_URL": TEST_DATABASE_URL},
        check=True,
        capture_output=True,
    )
    return TEST_DATABASE_URL


@pytest.fixture
async def session(migrated_db: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_db, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        # commit() в сервисах фиксирует savepoint, внешняя транзакция откатывается
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        yield session
        await session.close()
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def api(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def auth(user: User) -> dict[str, str]:
    token, _ = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


async def make_user(
    session: AsyncSession, email: str, role: UserRole, phone: str | None = None
) -> User:
    user = User(
        email=email,
        phone=phone,
        full_name=email.split("@")[0],
        password_hash=PASSWORD_HASH,
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def make_company(session: AsyncSession, inn: str, owner: User) -> Company:
    company = Company(
        inn=inn,
        ogrn="1027700000000",
        legal_form=LegalForm.OOO,
        name=f"ООО Тест {inn}",
        okved_main="47.11",
        registration_date=date(2019, 3, 1),
        region="Москва",
        legal_address="Москва, ул. Тестовая, 1",
    )
    session.add(company)
    await session.flush()
    session.add(
        CompanyMember(company_id=company.id, user_id=owner.id, role=CompanyMemberRole.OWNER)
    )
    await session.flush()
    return company


@pytest.fixture
async def client_user(session: AsyncSession) -> User:
    return await make_user(session, "client@example.com", UserRole.CLIENT, "+79990000101")


@pytest.fixture
async def other_client(session: AsyncSession) -> User:
    return await make_user(session, "other@example.com", UserRole.CLIENT, "+79990000102")


@pytest.fixture
async def analyst(session: AsyncSession) -> User:
    return await make_user(session, "analyst@example.com", UserRole.CREDIT_ANALYST)


@pytest.fixture
async def underwriter(session: AsyncSession) -> User:
    return await make_user(session, "underwriter@example.com", UserRole.UNDERWRITER)


@pytest.fixture
async def company(session: AsyncSession, client_user: User) -> Company:
    return await make_company(session, "7700000001", client_user)


@pytest.fixture
async def other_company(session: AsyncSession, other_client: User) -> Company:
    return await make_company(session, "7700000002", other_client)


@pytest.fixture
async def product(session: AsyncSession) -> CreditProduct:
    product = CreditProduct(
        code="working-capital",
        name="Оборотный кредит",
        description="Пополнение оборотных средств",
        credit_format=CreditFormat.LOAN,
        purposes=[LoanPurpose.WORKING_CAPITAL, LoanPurpose.BUSINESS_EXPANSION],
        min_amount=Decimal("300000"),
        max_amount=Decimal("10000000"),
        min_term_months=6,
        max_term_months=60,
        base_rate=Decimal("18.00"),
    )
    session.add(product)
    await session.flush()
    return product


@pytest.fixture
def draft_body(company: Company, product: CreditProduct) -> dict:
    return {
        "company_id": str(company.id),
        "product_id": str(product.id),
        "requested_amount": "3000000.00",
        "requested_term_months": 36,
        "purpose": "working_capital",
        "annual_revenue": "30000000.00",
    }


@pytest.fixture
async def draft(api: AsyncClient, client_user: User, draft_body: dict) -> dict:
    response = await api.post("/api/v1/applications", json=draft_body, headers=auth(client_user))
    assert response.status_code == 201, response.text
    return response.json()
