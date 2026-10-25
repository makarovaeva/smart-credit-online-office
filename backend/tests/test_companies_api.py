"""Профиль компании: привязка по ИНН, список и карточка, снимок реестра."""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyOwner, User
from app.services.companies import sync_company
from tests.conftest import auth
from tests.test_pipeline import start, submit

INN = "7701000001"


async def link(api: AsyncClient, user: User, inn: str = INN, **extra):
    return await api.post(
        "/api/v1/companies",
        json={"inn": inn, "member_role": "director"} | extra,
        headers=auth(user),
    )


async def test_link_company_builds_profile(api: AsyncClient, client_user: User) -> None:
    response = await link(api, client_user, actual_address="Москва, ул. Складская, 5")
    assert response.status_code == 201, response.text
    company = response.json()
    assert company["inn"] == INN
    assert company["name"].startswith("ООО «")
    assert company["full_name"].startswith("Общество с ограниченной ответственностью")
    assert company["okved_name"]
    assert company["tax_system"] in {"usn_income", "usn_income_expense", "osno"}
    assert company["actual_address"] == "Москва, ул. Складская, 5"
    assert company["member_role"] == "director"

    head = company["head"]
    assert head["position"] == "Генеральный директор"
    assert head["has_signing_authority"] is True
    # Руководитель - он же основной учредитель с правом подписи; в списке подписантов один раз
    assert company["signatories"] == [head["full_name"]]
    assert [o["share_percent"] for o in company["owners"]] == ["60.00", "40.00"]
    assert company["owners"][0]["has_signing_authority"] is True

    assert company["phone"].startswith("+7 495 ")
    assert company["email"] == f"finance@{INN}.example"
    assert company["settlement_account"]["bank_name"] == "АО «Альфа-Банк»"
    assert company["settlement_account"]["account_number"].startswith("40702810")


async def test_list_and_get_own_company(
    api: AsyncClient, client_user: User, other_client: User, analyst: User
) -> None:
    company_id = (await link(api, client_user)).json()["id"]

    listed = await api.get("/api/v1/companies", headers=auth(client_user))
    assert [c["id"] for c in listed.json()] == [company_id]
    me = await api.get("/api/v1/me", headers=auth(client_user))
    assert me.json()["companies"][0]["company_id"] == company_id

    url = f"/api/v1/companies/{company_id}"
    assert (await api.get(url, headers=auth(client_user))).json()["inn"] == INN
    assert (await api.get(url, headers=auth(other_client))).status_code == 404
    assert (await api.get(url, headers=auth(analyst))).status_code == 403


async def test_company_is_linked_once(
    api: AsyncClient, client_user: User, other_client: User
) -> None:
    assert (await link(api, client_user)).status_code == 201
    again = await link(api, client_user)
    assert again.status_code == 409
    assert "уже привязана" in again.json()["detail"]
    # Чужая уже обслуживаемая компания не привязывается без подтверждения полномочий
    assert (await link(api, other_client)).status_code == 409


async def test_unknown_inn(api: AsyncClient, client_user: User) -> None:
    assert (await link(api, client_user, inn="7701000099")).status_code == 404
    assert (await link(api, client_user, inn="123")).status_code == 422


async def test_sync_refreshes_snapshot_without_duplicates(
    api: AsyncClient, session: AsyncSession, client_user: User
) -> None:
    company_id = (await link(api, client_user, employees_count=42)).json()["id"]
    company = await sync_company(session, INN)
    await sync_company(session, INN)
    assert str(company.id) == company_id
    assert company.employees_count == 42
    owners = await session.scalar(
        select(func.count()).select_from(CompanyOwner).where(CompanyOwner.company_id == company.id)
    )
    assert owners == 2


async def test_backoffice_card_shows_profile(
    api: AsyncClient, session: AsyncSession, client_user: User, underwriter: User, product
) -> None:
    app_id = await start(api, session, client_user, product, INN)
    await submit(api, client_user, app_id)
    # Тестовая фабрика создаёт компанию без снимка реестра
    await sync_company(session, INN)
    detail = await api.get(f"/api/v1/backoffice/applications/{app_id}", headers=auth(underwriter))
    company = detail.json()["company"]
    assert company["head"]["full_name"] in company["signatories"]
    assert company["settlement_account"]["account_number"]
    assert detail.json()["owners"] == company["owners"]
