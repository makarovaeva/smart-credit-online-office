"""Сценарии заявки через API: черновик, согласия, подача, решения банка, оффер и выдача."""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    Company,
    CreditMemo,
    CreditProduct,
    InfoRequest,
    ScoringResult,
    User,
)
from app.models.enums import AiRecommendation, ApplicationStatus, RiskGrade, RiskZone
from tests.conftest import PASSWORD, auth

S = ApplicationStatus
ALL_CONSENTS = ["bki", "fns", "digital_profile"]


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


async def set_status(session: AsyncSession, application_id: str, status: S) -> Application:
    """Этапы конвейера ИИ ещё не реализованы - ставим статус напрямую."""
    application = await session.get(Application, application_id)
    application.status = status
    await session.flush()
    return application


async def at_underwriter(session: AsyncSession, application_id: str) -> CreditMemo:
    application = await set_status(session, application_id, S.UNDERWRITER_REVIEW)
    scoring = ScoringResult(
        application_id=application.id,
        model_version="test",
        score=720,
        risk_grade=RiskGrade.B,
        risk_zone=RiskZone.GREEN,
        confidence=Decimal("0.9"),
    )
    session.add(scoring)
    await session.flush()
    memo = CreditMemo(
        application_id=application.id,
        scoring_result_id=scoring.id,
        summary="Зелёная зона",
        ai_recommendation=AiRecommendation.APPROVE,
        recommended_amount=Decimal("3000000"),
        recommended_term_months=36,
        recommended_rate=Decimal("18"),
    )
    session.add(memo)
    await session.flush()
    return memo


async def statuses(api: AsyncClient, user: User, application_id: str) -> list[str]:
    response = await api.get(f"/api/v1/applications/{application_id}/history", headers=auth(user))
    return [item["to_status"] for item in response.json()]


# --- Авторизация ---


async def test_login_and_me(api: AsyncClient, client_user: User, company: Company) -> None:
    response = await api.post(
        "/api/v1/auth/login", json={"email": "CLIENT@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    me = await api.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["companies"][0]["company_id"] == str(company.id)


async def test_wrong_password(api: AsyncClient, client_user: User) -> None:
    response = await api.post(
        "/api/v1/auth/login", json={"email": "client@example.com", "password": "wrong"}
    )
    assert response.status_code == 401


async def test_requires_token_and_client_role(api: AsyncClient, analyst: User) -> None:
    assert (await api.get("/api/v1/applications")).status_code == 401
    bad = {"Authorization": "Bearer broken.token.value"}
    assert (await api.get("/api/v1/applications", headers=bad)).status_code == 401
    assert (await api.get("/api/v1/applications", headers=auth(analyst))).status_code == 403


# --- Черновик ---


async def test_create_draft(draft: dict) -> None:
    assert draft["number"].startswith("CR-")
    assert draft["status"] == "draft"
    assert draft["client_status"] == "draft"
    assert draft["available_actions"] == ["edit", "give_consents"]
    assert draft["requested_amount"] == "3000000.00"
    assert draft["version"] == 1


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"requested_amount": "50000000.00"}, "Сумма должна быть"),
        ({"requested_term_months": 120}, "Срок должен быть"),
        ({"purpose": "refinancing"}, "не подходит"),
    ],
)
async def test_create_checks_product(
    api: AsyncClient, client_user: User, draft_body: dict, change: dict, detail: str
) -> None:
    response = await api.post(
        "/api/v1/applications", json=draft_body | change, headers=auth(client_user)
    )
    assert response.status_code == 422
    assert detail in response.json()["detail"]


async def test_cannot_create_for_foreign_company(
    api: AsyncClient, client_user: User, other_company: Company, draft_body: dict
) -> None:
    body = draft_body | {"company_id": str(other_company.id)}
    response = await api.post("/api/v1/applications", json=body, headers=auth(client_user))
    assert response.status_code == 404


async def test_foreign_application_is_hidden(
    api: AsyncClient, draft: dict, other_client: User, other_company: Company
) -> None:
    headers = auth(other_client)
    assert (
        await api.get(f"/api/v1/applications/{draft['id']}", headers=headers)
    ).status_code == 404
    listing = await api.get("/api/v1/applications", headers=headers)
    assert listing.json()["total"] == 0


async def test_list_filters_by_status(api: AsyncClient, client_user: User, draft: dict) -> None:
    headers = auth(client_user)
    drafts = await api.get("/api/v1/applications", params={"status": "draft"}, headers=headers)
    assert [a["id"] for a in drafts.json()["items"]] == [draft["id"]]
    closed = await api.get("/api/v1/applications", params={"status": "closed"}, headers=headers)
    assert closed.json()["total"] == 0


async def test_update_draft_with_optimistic_lock(
    api: AsyncClient, client_user: User, draft: dict
) -> None:
    url = f"/api/v1/applications/{draft['id']}"
    body = {
        "requested_amount": "2500000.00",
        "has_collateral": True,
        "collateral_type": "equipment",
        "collateral_market_value": "4000000.00",
        "version": 1,
    }
    response = await api.patch(url, json=body, headers=auth(client_user))
    assert response.status_code == 200, response.text
    assert response.json()["requested_amount"] == "2500000.00"
    assert response.json()["version"] == 2

    stale = await api.patch(url, json=body, headers=auth(client_user))
    assert stale.status_code == 409

    # Без залога данные залога очищаются
    response = await api.patch(
        url, json={"has_collateral": False, "version": 2}, headers=auth(client_user)
    )
    assert response.json()["collateral_type"] is None
    assert response.json()["collateral_market_value"] is None


async def test_update_rejects_empty_required_field(
    api: AsyncClient, client_user: User, draft: dict
) -> None:
    response = await api.patch(
        f"/api/v1/applications/{draft['id']}",
        json={"requested_amount": None, "version": 1},
        headers=auth(client_user),
    )
    assert response.status_code == 422


async def test_terms_are_locked_after_submit(
    api: AsyncClient, session: AsyncSession, client_user: User, draft: dict
) -> None:
    application = await set_status(session, draft["id"], S.NEED_ADDITIONAL_DATA)
    url = f"/api/v1/applications/{draft['id']}"
    version = application.version
    locked = await api.patch(
        url, json={"requested_amount": "1000000.00", "version": version}, headers=auth(client_user)
    )
    assert locked.status_code == 409
    ok = await api.patch(
        url, json={"annual_ebitda": "5000000.00", "version": version}, headers=auth(client_user)
    )
    assert ok.status_code == 200


# --- Согласия, предварительный расчёт, подача ---


async def test_consents_start_data_collection(
    api: AsyncClient, client_user: User, draft: dict
) -> None:
    url = f"/api/v1/applications/{draft['id']}/consents"
    partial = await api.post(url, json={"types": ["bki"]}, headers=auth(client_user))
    assert partial.status_code == 422

    response = await api.post(url, json={"types": ALL_CONSENTS}, headers=auth(client_user))
    assert response.status_code == 200, response.text
    # Конвейер сразу собирает данные и делает предварительный расчёт
    assert response.json()["status"] == "pre_approved"
    assert (await statuses(api, client_user, draft["id"]))[:2] == [
        "data_collection",
        "pre_approved",
    ]
    consents = await api.get(url, headers=auth(client_user))
    assert sorted(c["type"] for c in consents.json()) == sorted(ALL_CONSENTS)

    again = await api.post(url, json={"types": ALL_CONSENTS}, headers=auth(client_user))
    assert again.status_code == 409


async def test_submit_requires_pre_approval(
    api: AsyncClient, session: AsyncSession, client_user: User, draft: dict
) -> None:
    url = f"/api/v1/applications/{draft['id']}/submit"
    assert (await api.post(url, headers=auth(client_user))).status_code == 409

    await set_status(session, draft["id"], S.PRE_APPROVED)
    response = await api.post(url, headers=auth(client_user))
    assert response.status_code == 200
    body = response.json()
    assert body["submitted_at"] is not None
    # Выручка в анкете (30 млн) расходится с ФНС - конвейер отправляет заявку аналитику
    assert body["status"] == "analyst_escalation"
    assert body["client_status"] == "under_review"
    assert "submitted" in await statuses(api, client_user, draft["id"])


async def test_submit_requires_collateral_data(
    api: AsyncClient, session: AsyncSession, client_user: User, draft: dict
) -> None:
    application = await set_status(session, draft["id"], S.PRE_APPROVED)
    application.has_collateral = True
    await session.flush()
    response = await api.post(
        f"/api/v1/applications/{draft['id']}/submit", headers=auth(client_user)
    )
    assert response.status_code == 422


async def test_decline_pre_approval_closes(
    api: AsyncClient, session: AsyncSession, client_user: User, draft: dict
) -> None:
    await set_status(session, draft["id"], S.PRE_APPROVED)
    response = await api.post(
        f"/api/v1/applications/{draft['id']}/pre-approval/decline", headers=auth(client_user)
    )
    body = response.json()
    assert body["status"] == "closed"
    assert body["close_reason"] == "pre_approval_declined"
    assert body["closed_at"] is not None
    assert body["available_actions"] == []


async def test_pre_approval_not_ready(api: AsyncClient, client_user: User, draft: dict) -> None:
    response = await api.get(
        f"/api/v1/applications/{draft['id']}/pre-approval", headers=auth(client_user)
    )
    assert response.status_code == 404


# --- Решения банка, оффер и выдача ---


async def test_approval_to_disbursement(
    api: AsyncClient, session: AsyncSession, client_user: User, underwriter: User, draft: dict
) -> None:
    app_id = draft["id"]
    await at_underwriter(session, app_id)
    decision = await api.post(
        f"/api/v1/backoffice/applications/{app_id}/decision",
        json={
            "decision_type": "approved",
            "approved_amount": "3000000.00",
            "approved_term_months": 36,
            "interest_rate": "18.00",
        },
        headers=auth(underwriter),
    )
    assert decision.status_code == 201, decision.text
    assert decision.json()["valid_until"] is not None

    headers = auth(client_user)
    application = (await api.get(f"/api/v1/applications/{app_id}", headers=headers)).json()
    assert application["client_status"] == "approved"
    assert application["available_actions"] == ["accept_offer", "reject_offer"]
    offer = (await api.get(f"/api/v1/applications/{app_id}/offer", headers=headers)).json()
    assert Decimal(offer["estimated_monthly_payment"]) == Decimal("108457.19")

    accepted = await api.post(f"/api/v1/applications/{app_id}/offer/accept", headers=headers)
    assert accepted.json()["status"] == "e_sign"
    signed = await api.post(
        f"/api/v1/applications/{app_id}/sign", json={"confirmation_code": "123456"}, headers=headers
    )
    assert signed.json()["status"] == "completed"
    assert signed.json()["client_status"] == "disbursed"
    assert signed.json()["disbursed_at"] is not None

    assert (await statuses(api, client_user, app_id))[-6:] == [
        "offer_generated",
        "offer_accepted",
        "contract_generation",
        "e_sign",
        "disbursement",
        "completed",
    ]


async def test_counter_offer_rejected(
    api: AsyncClient, session: AsyncSession, client_user: User, underwriter: User, draft: dict
) -> None:
    app_id = draft["id"]
    await at_underwriter(session, app_id)
    await api.post(
        f"/api/v1/backoffice/applications/{app_id}/decision",
        json={
            "decision_type": "conditional_approval",
            "approved_amount": "2000000.00",
            "approved_term_months": 48,
            "interest_rate": "20.00",
        },
        headers=auth(underwriter),
    )
    headers = auth(client_user)
    application = (await api.get(f"/api/v1/applications/{app_id}", headers=headers)).json()
    assert application["client_status"] == "counter_offer"
    assert "измененных условиях" in application["status_description"]

    rejected = await api.post(
        f"/api/v1/applications/{app_id}/offer/reject", json={"reason": "Мало"}, headers=headers
    )
    assert rejected.json()["status"] == "closed"
    assert rejected.json()["close_reason"] == "offer_rejected"
    offer = (await api.get(f"/api/v1/applications/{app_id}/offer", headers=headers)).json()
    assert offer["client_response"] == "rejected"


async def test_decline_requires_reason(
    api: AsyncClient, session: AsyncSession, underwriter: User, draft: dict
) -> None:
    await at_underwriter(session, draft["id"])
    url = f"/api/v1/backoffice/applications/{draft['id']}/decision"
    no_reason = await api.post(url, json={"decision_type": "declined"}, headers=auth(underwriter))
    assert no_reason.status_code == 422

    response = await api.post(
        url,
        json={
            "decision_type": "declined",
            "reasons": [{"code": "high_debt_burden", "message": "Высокая долговая нагрузка"}],
        },
        headers=auth(underwriter),
    )
    assert response.status_code == 201
    application = await session.get(Application, draft["id"])
    assert application.status == S.CLOSED
    assert application.close_reason == "underwriter_declined"


async def test_underwriter_requests_documents(
    api: AsyncClient, session: AsyncSession, underwriter: User, draft: dict
) -> None:
    await at_underwriter(session, draft["id"])
    response = await api.post(
        f"/api/v1/backoffice/applications/{draft['id']}/decision",
        json={
            "decision_type": "more_information_required",
            "more_info_target": "client",
            "info_request": {
                "message": "Нужна выписка по счёту за 12 месяцев",
                "requested_document_types": ["bank_statement"],
            },
        },
        headers=auth(underwriter),
    )
    assert response.status_code == 201, response.text
    application = await session.get(Application, draft["id"])
    assert application.status == S.NEED_ADDITIONAL_DATA
    assert application.decided_at is None
    info_request = await session.scalar(
        select(InfoRequest).where(InfoRequest.application_id == application.id)
    )
    assert info_request.created_by_id == underwriter.id


async def test_underwriter_requests_analyst_expertise(
    api: AsyncClient,
    session: AsyncSession,
    analyst: User,
    underwriter: User,
    draft: dict,
) -> None:
    await at_underwriter(session, draft["id"])
    base = f"/api/v1/backoffice/applications/{draft['id']}"
    no_comment = await api.post(
        f"{base}/decision",
        json={"decision_type": "more_information_required", "more_info_target": "credit_analyst"},
        headers=auth(underwriter),
    )
    assert no_comment.status_code == 422

    await api.post(
        f"{base}/decision",
        json={
            "decision_type": "more_information_required",
            "more_info_target": "credit_analyst",
            "comment": "Проверьте залог",
        },
        headers=auth(underwriter),
    )
    assert (await session.get(Application, draft["id"])).status == S.ANALYST_ESCALATION

    memo = await api.post(
        f"{base}/analyst-conclusion",
        json={
            "conclusion": "Залог ликвиден, сумму снизить",
            "recommendation": "counter_offer",
            "recommended_amount": "2500000.00",
        },
        headers=auth(analyst),
    )
    assert memo.status_code == 200, memo.text
    body = memo.json()
    assert body["ai_recommendation"] == "approve"
    assert body["analyst_recommendation"] == "counter_offer"
    assert body["recommended_amount"] == "2500000.00"
    assert body["recommended_term_months"] == 36
    assert (await session.get(Application, draft["id"])).status == S.UNDERWRITER_REVIEW


async def test_only_underwriter_decides(
    api: AsyncClient, session: AsyncSession, analyst: User, draft: dict
) -> None:
    await at_underwriter(session, draft["id"])
    response = await api.post(
        f"/api/v1/backoffice/applications/{draft['id']}/decision",
        json={"decision_type": "declined", "reasons": [{"code": "x", "message": "x"}]},
        headers=auth(analyst),
    )
    assert response.status_code == 403


async def test_decision_in_wrong_status(api: AsyncClient, underwriter: User, draft: dict) -> None:
    response = await api.post(
        f"/api/v1/backoffice/applications/{draft['id']}/decision",
        json={"decision_type": "declined", "reasons": [{"code": "x", "message": "x"}]},
        headers=auth(underwriter),
    )
    assert response.status_code == 409
