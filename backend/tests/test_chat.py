"""Чат с ИИ-агентом: разбор параметров, ответы по данным заявки, события, LLM и откат."""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ChatMessage, Company, CreditProduct, User
from app.models.enums import CollateralType, LoanPurpose
from app.services import llm
from app.services.chat import parse_loan_request
from tests.conftest import auth
from tests.test_pipeline import start, submit


@pytest.mark.parametrize(
    ("text", "amount", "term", "purpose", "collateral"),
    [
        ("3 млн на 2 года, пополнить оборотку", "3000000", 24, LoanPurpose.WORKING_CAPITAL, None),
        (
            "500 тыс на 18 месяцев на оборудование без залога",
            "500000",
            18,
            LoanPurpose.EQUIPMENT,
            False,
        ),
        ("5 000 000 ₽ на 3 года под залог оборудования", "5000000", 36, None, True),
        ("1,5 млн на полгода на закупку товара", "1500000", 6, LoanPurpose.WORKING_CAPITAL, None),
        ("Какой статус у заявки?", None, None, None, None),
    ],
)
def test_parse_loan_request(text, amount, term, purpose, collateral) -> None:
    request = parse_loan_request(text)
    assert request.amount == (Decimal(amount) if amount else None)
    assert request.term_months == term
    assert request.purpose == purpose
    assert request.has_collateral is collateral


def test_parse_collateral_type() -> None:
    request = parse_loan_request("2 млн на год под залог складского помещения")
    assert request.term_months == 12
    assert request.collateral_type == CollateralType.COMMERCIAL_REAL_ESTATE


async def send(api: AsyncClient, user: User, company_id, text: str, **extra):
    response = await api.post(
        "/api/v1/chat/messages",
        json={"company_id": str(company_id), "content": text} | extra,
        headers=auth(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def messages(api: AsyncClient, user: User, company_id, **query) -> list[dict]:
    response = await api.get(
        "/api/v1/chat/messages",
        params={"company_id": str(company_id)} | query,
        headers=auth(user),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_loan_parameters_give_confirmation_card(
    api: AsyncClient, client_user: User, company: Company, product: CreditProduct
) -> None:
    exchange = await send(api, client_user, company.id, "Нужно 3 млн на 2 года на оборотку")
    assert exchange["message"]["sender_type"] == "client"
    reply = exchange["reply"]
    assert reply["sender_type"] == "ai_agent"
    assert reply["message_type"] == "confirmation_card"
    assert reply["generated_by"] == "rules"
    assert reply["reply_to_id"] == exchange["message"]["id"]
    card = reply["card_payload"]
    assert card["fields"]["amount"] == "3000000.00"
    assert card["fields"]["term_months"] == 24
    assert card["fields"]["purpose"] == "working_capital"
    assert card["fields"]["product_id"] == str(product.id)
    assert card["action"] == {"action_type": "create_application", "status": "pending"}
    assert "Оборотный кредит" in reply["content"]

    history = await messages(api, client_user, company.id)
    assert [m["id"] for m in history] == [exchange["message"]["id"], reply["id"]]


async def test_incomplete_parameters_ask_for_the_rest(
    api: AsyncClient, client_user: User, company: Company, product: CreditProduct
) -> None:
    reply = (await send(api, client_user, company.id, "Хочу 2 млн"))["reply"]
    assert reply["card_payload"]["action"]["status"] == "incomplete"
    assert "срок" in reply["content"]


async def test_repeat_with_same_key_is_not_duplicated(
    api: AsyncClient, session: AsyncSession, client_user: User, company: Company
) -> None:
    first = await send(api, client_user, company.id, "Привет", client_message_id="k-1")
    again = await send(api, client_user, company.id, "Привет", client_message_id="k-1")
    assert again["message"]["id"] == first["message"]["id"]
    assert again["reply"]["id"] == first["reply"]["id"]
    count = await session.scalar(select(func.count()).select_from(ChatMessage))
    assert count == 2


async def test_status_and_auto_decline_in_chat(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000002")
    application = await submit(api, client_user, app_id)
    assert application["status"] == "closed"
    company_id = application["company_id"]

    # Агент сам сообщил об отказе с причиной
    [notice] = await messages(api, client_user, company_id, application_id=app_id)
    assert notice["message_type"] == "rejection_notice"
    assert "банкротство" in notice["content"].lower()

    reply = (await send(api, client_user, company_id, "Почему отказ?", application_id=app_id))[
        "reply"
    ]
    assert reply["message_type"] == "rejection_notice"
    assert "банкротство" in reply["content"].lower()
    advice = (
        await send(api, client_user, company_id, "Что можно исправить?", application_id=app_id)
    )["reply"]
    assert "Что можно сделать" in advice["content"]
    assert "банкротства" in advice["content"]
    status = (await send(api, client_user, company_id, "Что с заявкой?", application_id=app_id))[
        "reply"
    ]
    assert application["number"] in status["content"]


async def test_document_request_in_chat(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000019")
    application = await submit(api, client_user, app_id)
    company_id = application["company_id"]
    [notice] = await messages(api, client_user, company_id, application_id=app_id)
    assert notice["message_type"] == "document_request"
    assert len(notice["info_request_ids"]) == 1

    reply = (
        await send(api, client_user, company_id, "Какие документы нужны?", application_id=app_id)
    )["reply"]
    assert reply["message_type"] == "document_request"
    assert "выписка" in reply["content"]


async def test_chat_access(
    api: AsyncClient,
    client_user: User,
    other_client: User,
    analyst: User,
    company: Company,
    other_company: Company,
    draft: dict,
) -> None:
    response = await api.get(
        "/api/v1/chat/messages", params={"company_id": str(company.id)}, headers=auth(other_client)
    )
    assert response.status_code == 404
    response = await api.get(
        "/api/v1/chat/messages", params={"company_id": str(company.id)}, headers=auth(analyst)
    )
    assert response.status_code == 403
    # Заявка чужой компании в своём диалоге
    response = await api.post(
        "/api/v1/chat/messages",
        json={
            "company_id": str(other_company.id),
            "application_id": draft["id"],
            "content": "Статус?",
        },
        headers=auth(other_client),
    )
    assert response.status_code == 404


def _mock_llm(monkeypatch: pytest.MonkeyPatch, answer) -> list[dict]:
    """answer(payload) -> ответ сервера или исключение."""
    calls: list[dict] = []

    def post(url, payload, headers, timeout):
        assert url == "http://llm.test/v1/chat/completions"
        calls.append(payload)
        return answer(payload)

    monkeypatch.setattr(get_settings(), "llm_base_url", "http://llm.test/v1")
    monkeypatch.setattr(llm, "_post", post)
    return calls


async def test_llm_phrases_reply_from_facts(
    api: AsyncClient,
    client_user: User,
    company: Company,
    product: CreditProduct,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_llm(
        monkeypatch,
        lambda payload: {"choices": [{"message": {"content": "Понял вас: 3 млн на 2 года."}}]},
    )
    reply = (await send(api, client_user, company.id, "3 млн на 2 года на оборотку"))["reply"]
    assert reply["content"] == "Понял вас: 3 млн на 2 года."
    assert reply["generated_by"] == f"llm:{get_settings().llm_model}"
    # Карточку строит backend, не модель
    assert reply["card_payload"]["fields"]["amount"] == "3000000.00"
    system = calls[0]["messages"][0]["content"]
    assert company.inn in system
    assert "Оборотный кредит" in system


async def test_llm_failure_falls_back_to_rules(
    api: AsyncClient, client_user: User, company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(payload):
        raise OSError("connection refused")

    _mock_llm(monkeypatch, unavailable)
    reply = (await send(api, client_user, company.id, "Привет"))["reply"]
    assert reply["generated_by"] == "rules"
    assert reply["content"].startswith("Здравствуйте")


async def test_dialog_before_application_joins_it(
    api: AsyncClient, client_user: User, company: Company, draft_body: dict
) -> None:
    exchange = await send(api, client_user, company.id, "3 млн на 3 года на оборотку")
    created = await api.post("/api/v1/applications", json=draft_body, headers=auth(client_user))
    app_id = created.json()["id"]
    history = await messages(api, client_user, company.id, application_id=app_id)
    assert [m["id"] for m in history] == [exchange["message"]["id"], exchange["reply"]["id"]]
    # Теперь черновик есть: карточка предлагает обновить его
    reply = (await send(api, client_user, company.id, "Лучше 4 млн", application_id=app_id))[
        "reply"
    ]
    assert reply["card_payload"]["action"]["action_type"] == "update_application"
    assert reply["card_payload"]["fields"]["amount"] == "4000000.00"
    assert reply["card_payload"]["fields"]["term_months"] == 36


async def test_free_text_during_open_request_points_to_answer(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    analyst: User,
    draft: dict,
) -> None:
    from tests.test_applications_api import set_status

    application = await set_status(session, draft["id"], "analyst_escalation")
    application.assignee_id = analyst.id
    await session.flush()
    await api.post(
        f"/api/v1/backoffice/applications/{draft['id']}/info-requests",
        json={"message": "Нужно: пояснение по структуре бизнеса"},
        headers=auth(analyst),
    )
    reply = (
        await send(
            api,
            client_user,
            draft["company_id"],
            "У нас два учредителя",
            application_id=draft["id"],
        )
    )["reply"]
    assert reply["message_type"] == "document_request"
    assert "Ваш ответ банку" in reply["content"]
    assert "пояснение по структуре бизнеса" in reply["content"]
