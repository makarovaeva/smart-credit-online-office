"""Кредитный конвейер через API на демо-ИНН: обогащение -> скоринг -> политика -> маршрутизация."""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.synthetic import DEMO_UNAVAILABLE
from app.models import (
    Application,
    CreditMemo,
    CreditProduct,
    ExternalCheck,
    InfoRequest,
    PreApproval,
    ScoringResult,
    User,
)
from app.models.enums import CheckSource, CheckStatus
from app.services import scoring
from tests.conftest import auth, make_company

ALL_CONSENTS = ["bki", "fns", "digital_profile"]


async def start(
    api: AsyncClient,
    session: AsyncSession,
    user: User,
    product: CreditProduct,
    inn: str,
    amount: str = "3000000.00",
    **extra: str,
) -> str:
    """Черновик -> согласия -> предварительный расчёт. Возвращает id заявки."""
    company = await make_company(session, inn, user)
    body = {
        "company_id": str(company.id),
        "product_id": str(product.id),
        "requested_amount": amount,
        "requested_term_months": 36,
        "purpose": "working_capital",
    } | extra
    created = await api.post("/api/v1/applications", json=body, headers=auth(user))
    app_id = created.json()["id"]
    response = await api.post(
        f"/api/v1/applications/{app_id}/consents",
        json={"types": ALL_CONSENTS},
        headers=auth(user),
    )
    assert response.status_code == 200, response.text
    return app_id


async def submit(api: AsyncClient, user: User, app_id: str) -> dict:
    response = await api.post(f"/api/v1/applications/{app_id}/submit", headers=auth(user))
    assert response.status_code == 200, response.text
    return response.json()


async def latest(session: AsyncSession, model, app_id: str):
    return await session.scalar(
        select(model).where(model.application_id == app_id).order_by(model.created_at.desc())
    )


async def history(api: AsyncClient, user: User, app_id: str) -> list[dict]:
    response = await api.get(f"/api/v1/applications/{app_id}/history", headers=auth(user))
    return response.json()


async def test_green_zone_goes_to_underwriter(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000001")

    pre = (
        await api.get(f"/api/v1/applications/{app_id}/pre-approval", headers=auth(client_user))
    ).json()
    assert Decimal(pre["approval_probability"]) >= Decimal("0.8")
    assert pre["amount_max"] == "3000000.00"
    assert pre["recommendations"] == []

    body = await submit(api, client_user, app_id)
    assert body["status"] == "underwriter_review"
    assert [h["to_status"] for h in await history(api, client_user, app_id)][2:] == [
        "submitted",
        "ai_verification",
        "ai_financial_analysis",
        "ai_risk_scoring",
        "decision_routing",
        "underwriter_review",
    ]

    result = await latest(session, ScoringResult, app_id)
    assert result.risk_zone == "green"
    assert result.dscr > Decimal("1.1")
    assert result.factors
    memo = await latest(session, CreditMemo, app_id)
    assert memo.scoring_result_id == result.id
    assert memo.ai_recommendation == "approve"
    assert memo.recommended_amount == Decimal("3000000")
    assert "Зона риска: green" in memo.summary


async def test_counter_offer_above_auto_approval_limit(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000001", amount="8000000.00")
    pre = await latest(session, PreApproval, app_id)
    assert pre.amount_max == Decimal("5000000")
    assert pre.recommendations[0]["code"] == "auto_approval_limit"

    assert (await submit(api, client_user, app_id))["status"] == "underwriter_review"
    memo = await latest(session, CreditMemo, app_id)
    assert memo.ai_recommendation == "counter_offer"
    assert memo.recommended_amount == Decimal("5000000")
    assert memo.counter_offer_adjustments[0]["scenario"] == "auto_approval_limit"


async def test_stop_factor_is_auto_declined(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000002")
    pre = await latest(session, PreApproval, app_id)
    assert pre.approval_probability == Decimal("0.05")
    assert pre.recommendations[0]["code"] == "bankruptcy"

    body = await submit(api, client_user, app_id)
    assert body["status"] == "closed"
    assert body["close_reason"] == "auto_declined"
    assert body["client_status"] == "closed"
    assert "не готов предоставить финансирование" in body["status_description"]
    last = (await history(api, client_user, app_id))[-1]
    assert last["actor_type"] == "system"
    assert last["comment"].startswith("Автоматический отказ: Действующее банкротство")

    memo = await latest(session, CreditMemo, app_id)
    assert memo.ai_recommendation == "decline"
    assert memo.recommended_amount is None


async def test_young_business_goes_to_analyst(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000007")
    assert (await submit(api, client_user, app_id))["status"] == "analyst_escalation"
    result = await latest(session, ScoringResult, app_id)
    assert result.risk_zone == "yellow"
    assert [r["code"] for r in result.escalation_reasons] == ["young_business"]


async def test_unavailable_source_is_saved_and_escalated(
    api: AsyncClient, session: AsyncSession, client_user: User, product: CreditProduct
) -> None:
    app_id = await start(api, session, client_user, product, "7701000011")
    assert (await submit(api, client_user, app_id))["status"] == "analyst_escalation"

    checks = await session.scalars(
        select(ExternalCheck).where(
            ExternalCheck.application_id == app_id, ExternalCheck.source == CheckSource.BKI
        )
    )
    assert {c.status for c in checks} == {CheckStatus.FAILED}
    result = await latest(session, ScoringResult, app_id)
    assert "missing_external_data" in [r["code"] for r in result.escalation_reasons]
    assert result.confidence < Decimal("0.8")


async def test_missing_financials_requests_documents(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    product: CreditProduct,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inn = "7701000555"
    monkeypatch.setitem(DEMO_UNAVAILABLE, inn, frozenset({CheckSource.FNS}))
    app_id = await start(api, session, client_user, product, inn)

    body = await submit(api, client_user, app_id)
    assert body["status"] == "need_additional_data"
    assert body["client_status"] == "documents_required"
    info_request = await latest(session, InfoRequest, app_id)
    assert info_request.created_by_id is None
    assert "financial_statement" in info_request.requested_document_types


async def test_pipeline_failure_keeps_client_command(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    product: CreditProduct,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_id = await start(api, session, client_user, product, "7701000001")

    async def broken(self, features):
        raise RuntimeError("scoring is down")

    monkeypatch.setattr(scoring.RuleBasedScoring, "score", broken)
    body = await submit(api, client_user, app_id)
    assert body["status"] == "submitted"
    application = await session.get(Application, app_id)
    assert application.status == "submitted"


async def test_underwriter_picks_alternative_offer(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    underwriter: User,
    product: CreditProduct,
) -> None:
    # Долговая нагрузка на запрошенных условиях выше 50%: пограничный риск
    app_id = await start(api, session, client_user, product, "7712345678", amount="5000000.00")
    pre = await latest(session, PreApproval, app_id)
    assert any(r["code"] == "alternative_longer_term" for r in pre.recommendations)
    assert pre.amount_max == Decimal("5000000")

    assert (await submit(api, client_user, app_id))["status"] == "underwriter_review"
    memo = await latest(session, CreditMemo, app_id)
    assert memo.ai_recommendation == "counter_offer"
    longer = next(o for o in memo.alternative_offers if o["kind"] == "longer_term")
    assert longer["amount"] == "5000000.00"

    url = f"/api/v1/backoffice/applications/{app_id}/decision"
    wrong = await api.post(
        url,
        json={"decision_type": "approved", "alternative_offer": "longer_term"},
        headers=auth(underwriter),
    )
    assert wrong.status_code == 422

    decision = await api.post(
        url,
        json={"decision_type": "conditional_approval", "alternative_offer": "longer_term"},
        headers=auth(underwriter),
    )
    assert decision.status_code == 201, decision.text
    offer = (
        await api.get(f"/api/v1/applications/{app_id}/offer", headers=auth(client_user))
    ).json()
    assert offer["decision_type"] == "conditional_approval"
    assert offer["approved_amount"] == "5000000.00"
    assert offer["approved_term_months"] == longer["term_months"]
    assert offer["interest_rate"] == longer["rate"]
