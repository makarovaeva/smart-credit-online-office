"""Очереди сотрудников: автоназначение, «свои» заявки, доступ, переназначение."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, CreditProduct, User
from app.models.enums import UserRole
from app.schemas.auth import normalize_phone
from tests.conftest import auth, make_user
from tests.test_pipeline import start, submit

QUEUE = "/api/v1/backoffice/applications"


@pytest.fixture
async def underwriter2(session: AsyncSession) -> User:
    return await make_user(session, "underwriter2@example.com", UserRole.UNDERWRITER)


@pytest.fixture
async def admin(session: AsyncSession) -> User:
    return await make_user(session, "admin@example.com", UserRole.ADMIN)


async def green_application(
    api: AsyncClient, session: AsyncSession, client: User, product: CreditProduct, inn: str
) -> str:
    app_id = await start(api, session, client, product, inn)
    assert (await submit(api, client, app_id))["status"] == "underwriter_review"
    return app_id


async def queue(api: AsyncClient, user: User, **params) -> list[str]:
    response = await api.get(QUEUE, params=params, headers=auth(user))
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_normalize_phone() -> None:
    for raw in ("8 (999) 123-45-67", "+7 999 123 45 67", "9991234567", "79991234567"):
        assert normalize_phone(raw) == "+79991234567"
    with pytest.raises(ValueError):
        normalize_phone("+1 555 0100")


async def test_assigned_to_least_loaded_and_queues_are_separate(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    product: CreditProduct,
    underwriter: User,
    underwriter2: User,
    analyst: User,
    admin: User,
) -> None:
    first = await green_application(api, session, client_user, product, "7701000001")
    second = await green_application(api, session, client_user, product, "770100000001")
    young = await start(api, session, client_user, product, "7701000007")
    await submit(api, client_user, young)

    assignees = {(await session.get(Application, app_id)).assignee_id for app_id in (first, second)}
    assert assignees == {underwriter.id, underwriter2.id}
    assert (await session.get(Application, young)).assignee_id == analyst.id

    mine = await queue(api, underwriter)
    others = await queue(api, underwriter2)
    assert len(mine) == len(others) == 1
    assert set(mine) != set(others)
    assert await queue(api, analyst) == [young]
    assert set(await queue(api, admin)) == {first, second, young}

    # Фильтры по статусу и зоне риска
    assert await queue(api, analyst, status="underwriter_review") == []
    assert await queue(api, admin, risk_zone="yellow") == [young]


async def test_processed_applications_stay_in_queue(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    product: CreditProduct,
    underwriter: User,
) -> None:
    app_id = await green_application(api, session, client_user, product, "7701000001")
    response = await api.post(
        f"{QUEUE}/{app_id}/decision",
        json={
            "decision_type": "approved",
            "approved_amount": "3000000.00",
            "approved_term_months": 36,
            "interest_rate": "18.00",
        },
        headers=auth(underwriter),
    )
    assert response.status_code == 201, response.text
    assert (await session.get(Application, app_id)).assignee_id is None
    assert await queue(api, underwriter, status="offer_generated") == [app_id]
    assert await queue(api, underwriter, status="underwriter_review") == []


async def test_detail_and_decision_only_for_own(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    product: CreditProduct,
    underwriter: User,
    underwriter2: User,
) -> None:
    app_id = await green_application(api, session, client_user, product, "7701000001")
    owner, stranger = (
        (underwriter, underwriter2)
        if (await session.get(Application, app_id)).assignee_id == underwriter.id
        else (underwriter2, underwriter)
    )

    detail = await api.get(f"{QUEUE}/{app_id}", headers=auth(owner))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["assignee_id"] == str(owner.id)
    assert body["credit_memo"]["ai_recommendation"] == "approve"
    assert body["scoring"]["risk_zone"] == "green"
    assert len(body["external_checks"]) == 8
    assert body["company"]["inn"] == "7701000001"

    assert (await api.get(f"{QUEUE}/{app_id}", headers=auth(stranger))).status_code == 404
    assert (await api.get(f"{QUEUE}/{app_id}", headers=auth(client_user))).status_code == 403
    decision = await api.post(
        f"{QUEUE}/{app_id}/decision",
        json={"decision_type": "declined", "reasons": [{"code": "x", "message": "x"}]},
        headers=auth(stranger),
    )
    assert decision.status_code == 403


async def test_expertise_returns_to_the_same_underwriter(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    product: CreditProduct,
    underwriter: User,
    underwriter2: User,
    analyst: User,
) -> None:
    app_id = await green_application(api, session, client_user, product, "7701000001")
    owner_id = (await session.get(Application, app_id)).assignee_id
    owner = underwriter if owner_id == underwriter.id else underwriter2

    await api.post(
        f"{QUEUE}/{app_id}/decision",
        json={
            "decision_type": "more_information_required",
            "more_info_target": "credit_analyst",
            "comment": "Проверьте структуру владения",
        },
        headers=auth(owner),
    )
    assert (await session.get(Application, app_id)).assignee_id == analyst.id

    response = await api.post(
        f"{QUEUE}/{app_id}/analyst-conclusion",
        json={"conclusion": "Владение прозрачное", "recommendation": "approve"},
        headers=auth(analyst),
    )
    assert response.status_code == 200, response.text
    assert (await session.get(Application, app_id)).assignee_id == owner.id
    # Аналитик видит заявку, с которой работал
    assert app_id in await queue(api, analyst)


async def test_reassign(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    product: CreditProduct,
    underwriter: User,
    underwriter2: User,
    analyst: User,
) -> None:
    app_id = await green_application(api, session, client_user, product, "7701000001")
    application = await session.get(Application, app_id)
    owner, colleague = (
        (underwriter, underwriter2)
        if application.assignee_id == underwriter.id
        else (underwriter2, underwriter)
    )
    url = f"{QUEUE}/{app_id}/assign"

    wrong_role = await api.post(url, json={"assignee_id": str(analyst.id)}, headers=auth(owner))
    assert wrong_role.status_code == 422

    response = await api.post(url, json={"assignee_id": str(colleague.id)}, headers=auth(owner))
    assert response.status_code == 200, response.text
    assert response.json()["assignee_id"] == str(colleague.id)
    assert await queue(api, colleague) == [app_id]
    assert await queue(api, owner) == []


async def test_products_catalog(api: AsyncClient, product: CreditProduct) -> None:
    products = (await api.get("/api/v1/products")).json()
    assert [p["code"] for p in products] == ["working-capital"]
    one = await api.get(f"/api/v1/products/{product.id}")
    assert one.json()["base_rate"] == "18.00"
