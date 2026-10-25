"""Отмена заявки и одна заявка в работе, объяснение отказа, уведомления, подбор продукта,
запросы экспертизы и управление дозапросами."""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ChatMessage,
    CreditProduct,
    InfoRequest,
    InternalRequest,
    Notification,
    User,
)
from app.models.enums import ApplicationStatus
from tests.conftest import auth
from tests.test_applications_api import at_underwriter, set_status
from tests.test_pipeline import start, submit

S = ApplicationStatus


async def decide(api: AsyncClient, underwriter: User, app_id: str, body: dict):
    response = await api.post(
        f"/api/v1/backoffice/applications/{app_id}/decision", json=body, headers=auth(underwriter)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def notes(session: AsyncSession, user: User) -> list[Notification]:
    rows = await session.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at)
    )
    return list(rows)


# --- Отмена и одна заявка в работе ---


async def test_one_active_application_and_cancel(
    api: AsyncClient, client_user: User, draft: dict, draft_body: dict
) -> None:
    again = await api.post("/api/v1/applications", json=draft_body, headers=auth(client_user))
    assert again.status_code == 409
    assert draft["number"] in again.json()["detail"]

    cancelled = await api.post(
        f"/api/v1/applications/{draft['id']}/cancel", headers=auth(client_user)
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["status"] == "closed"
    assert body["close_reason"] == "client_cancelled"
    assert body["available_actions"] == []
    assert body["status_description"] == "Заявка отменена по вашему запросу"

    created = await api.post("/api/v1/applications", json=draft_body, headers=auth(client_user))
    assert created.status_code == 201


async def test_cancel_closes_open_requests(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000019")
    assert (await submit(api, client_user, app_id))["status"] == "need_additional_data"
    response = await api.post(f"/api/v1/applications/{app_id}/cancel", headers=auth(client_user))
    assert response.status_code == 200
    statuses = await session.scalars(
        select(InfoRequest.status).where(InfoRequest.application_id == app_id)
    )
    assert set(statuses) == {"cancelled"}
    chat = await session.scalar(
        select(ChatMessage.content)
        .where(ChatMessage.application_id == app_id)
        .order_by(ChatMessage.created_at.desc())
    )
    assert chat == "Заявка отменена по вашему запросу."


async def test_cannot_cancel_after_offer(
    api: AsyncClient, session: AsyncSession, client_user: User, draft: dict
) -> None:
    await set_status(session, draft["id"], S.OFFER_GENERATED)
    response = await api.post(
        f"/api/v1/applications/{draft['id']}/cancel", headers=auth(client_user)
    )
    assert response.status_code == 409


# --- Объяснение отказа ---


async def test_auto_decline_is_explained(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000002")
    body = await submit(api, client_user, app_id)
    [reason] = body["decline_reasons"]
    assert reason["code"] == "bankruptcy"
    assert reason["message"] == "Действующее банкротство"
    assert "банкротства" in reason["advice"]


async def test_underwriter_decline_is_explained(
    api: AsyncClient, session: AsyncSession, client_user: User, underwriter: User, draft: dict
) -> None:
    await at_underwriter(session, draft["id"])
    await decide(
        api,
        underwriter,
        draft["id"],
        {
            "decision_type": "declined",
            "reasons": [{"code": "low_turnover", "message": "Обороты не покрывают платёж"}],
        },
    )
    body = (await api.get(f"/api/v1/applications/{draft['id']}", headers=auth(client_user))).json()
    assert body["decline_reasons"] == [
        {"code": "low_turnover", "message": "Обороты не покрывают платёж", "advice": None}
    ]


# --- Уведомления ---


async def test_notifications_for_client_and_assignee(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    other_client: User,
    underwriter: User,
    product: CreditProduct,
) -> None:
    app_id = await start(api, session, client_user, product, "7701000001")
    await submit(api, client_user, app_id)
    [assigned] = await notes(session, underwriter)
    assert assigned.type == "application_assigned"
    assert str(assigned.application_id) == app_id

    await decide(
        api,
        underwriter,
        app_id,
        {
            "decision_type": "approved",
            "approved_amount": "3000000.00",
            "approved_term_months": 36,
            "interest_rate": "18.00",
        },
    )
    page = (await api.get("/api/v1/notifications", headers=auth(client_user))).json()
    assert page["unread"] == 1
    [offer] = page["items"]
    assert offer["type"] == "offer_ready"
    assert offer["title"].startswith("Предложение банка готово")

    url = f"/api/v1/notifications/{offer['id']}/read"
    assert (await api.post(url, headers=auth(other_client))).status_code == 404
    assert (await api.post(url, headers=auth(client_user))).status_code == 204
    unread = await api.get(
        "/api/v1/notifications", params={"unread_only": True}, headers=auth(client_user)
    )
    assert unread.json()["items"] == []
    assert unread.json()["unread"] == 0

    assert (
        await api.post("/api/v1/notifications/read-all", headers=auth(underwriter))
    ).status_code == 204
    assert all(n.read_at for n in await notes(session, underwriter))


# --- Подбор продукта ---


async def test_product_match(
    api: AsyncClient, product: CreditProduct, session: AsyncSession
) -> None:
    session.add(
        CreditProduct(
            code="equipment",
            name="Кредит на оборудование",
            description="Под залог оборудования",
            credit_format="loan",
            purposes=["equipment"],
            min_amount=Decimal("500000"),
            max_amount=Decimal("30000000"),
            min_term_months=12,
            max_term_months=84,
            base_rate=Decimal("16.50"),
            requires_collateral=True,
        )
    )
    await session.flush()
    response = await api.post(
        "/api/v1/products/match",
        json={"purpose": "working_capital", "amount": "3000000", "term_months": 24},
    )
    assert response.status_code == 200, response.text
    first, second = response.json()
    assert first["product"]["code"] == "working-capital"
    assert first["fits"] is True
    assert Decimal(first["estimated_monthly_payment"]) > Decimal("140000")
    assert second["fits"] is False
    assert "Нужен залог" in second["notes"]


# --- Запрос экспертизы ---


async def _expertise(api, session, underwriter, analyst, draft) -> InternalRequest:
    await at_underwriter(session, draft["id"])
    await decide(
        api,
        underwriter,
        draft["id"],
        {
            "decision_type": "more_information_required",
            "more_info_target": "credit_analyst",
            "comment": "Проверьте контрагентов",
        },
    )
    request = await session.scalar(
        select(InternalRequest).where(InternalRequest.application_id == draft["id"])
    )
    assert request.status == "open"
    assert request.message == "Проверьте контрагентов"
    application = await session.get(Application, draft["id"])
    assert application.assignee_id == analyst.id
    return request


async def test_expertise_request_accept_and_return(
    api: AsyncClient, session: AsyncSession, underwriter: User, analyst: User, draft: dict
) -> None:
    request = await _expertise(api, session, underwriter, analyst, draft)
    base = f"/api/v1/backoffice/applications/{draft['id']}"

    queue = await api.get("/api/v1/backoffice/applications", headers=auth(analyst))
    assert queue.json()["items"][0]["expertise_request"] == "open"

    url = f"{base}/internal-requests/{request.id}"
    assert (await api.post(f"{url}/accept", headers=auth(underwriter))).status_code == 403
    accepted = await api.post(f"{url}/accept", headers=auth(analyst))
    assert accepted.json()["status"] == "accepted"

    returned = await api.post(
        f"{url}/return",
        json={"comment": "Нужна выписка, без неё вывода нет"},
        headers=auth(analyst),
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["status"] == "returned"
    application = await session.get(Application, draft["id"])
    await session.refresh(application)
    assert application.status == S.UNDERWRITER_REVIEW
    assert application.assignee_id == underwriter.id
    assert "request_returned" in [n.type for n in await notes(session, underwriter)]
    assert (await api.post(f"{url}/accept", headers=auth(analyst))).status_code == 409


async def test_expertise_request_cancel_remind_and_conclusion(
    api: AsyncClient, session: AsyncSession, underwriter: User, analyst: User, draft: dict
) -> None:
    request = await _expertise(api, session, underwriter, analyst, draft)
    base = f"/api/v1/backoffice/applications/{draft['id']}"
    url = f"{base}/internal-requests/{request.id}"

    assert (await api.post(f"{url}/remind", headers=auth(underwriter))).status_code == 200
    assert "reminder" in [n.type for n in await notes(session, analyst)]
    cancelled = await api.post(f"{url}/cancel", headers=auth(underwriter))
    assert cancelled.json()["status"] == "cancelled"
    application = await session.get(Application, draft["id"])
    await session.refresh(application)
    assert application.status == S.UNDERWRITER_REVIEW

    # Новый запрос закрывается заключением аналитика
    await decide(
        api,
        underwriter,
        draft["id"],
        {
            "decision_type": "more_information_required",
            "more_info_target": "credit_analyst",
            "comment": "Оцените залог",
        },
    )
    conclusion = await api.post(
        f"{base}/analyst-conclusion",
        json={"conclusion": "Залог ликвиден", "recommendation": "approve"},
        headers=auth(analyst),
    )
    assert conclusion.status_code == 200, conclusion.text
    detail = (await api.get(base, headers=auth(underwriter))).json()
    statuses = [(r["status"], r["response_comment"]) for r in detail["internal_requests"]]
    assert statuses == [
        ("cancelled", "Андеррайтер отозвал запрос экспертизы"),
        ("completed", "Залог ликвиден"),
    ]


# --- Дозапрос клиенту: напоминание и отзыв ---


async def test_info_request_remind_and_cancel(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    underwriter: User,
    analyst: User,
    draft: dict,
) -> None:
    await at_underwriter(session, draft["id"])
    await decide(
        api,
        underwriter,
        draft["id"],
        {
            "decision_type": "more_information_required",
            "more_info_target": "client",
            "info_request": {"message": "Пришлите КУДИР", "requested_document_types": ["kudir"]},
        },
    )
    request = await session.scalar(
        select(InfoRequest).where(InfoRequest.application_id == draft["id"])
    )
    base = f"/api/v1/backoffice/applications/{draft['id']}/info-requests/{request.id}"

    # Дозапрос андеррайтера - не аналитику управлять им
    assert (await api.post(f"{base}/remind", headers=auth(analyst))).status_code == 404
    reminded = await api.post(f"{base}/remind", headers=auth(underwriter))
    assert reminded.status_code == 200, reminded.text
    reminder = await session.scalar(
        select(ChatMessage.content)
        .where(ChatMessage.application_id == draft["id"])
        .order_by(ChatMessage.created_at.desc())
    )
    assert reminder.startswith("Напоминаю")
    assert "reminder" in [n.type for n in await notes(session, client_user)]

    cancelled = await api.post(f"{base}/cancel", headers=auth(underwriter))
    assert cancelled.json()["status"] == "cancelled"
    application = await session.get(Application, draft["id"])
    await session.refresh(application)
    assert application.status == S.UNDERWRITER_REVIEW
