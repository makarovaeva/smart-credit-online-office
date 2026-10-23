"""Договор, симуляция подписания и выдачи, раздел «Кредиты»."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoanContract, PaymentScheduleItem, User
from app.services import loans
from tests.conftest import auth
from tests.test_applications_api import at_underwriter

APPROVE = {
    "decision_type": "approved",
    "approved_amount": "3000000.00",
    "approved_term_months": 36,
    "interest_rate": "18.00",
}
SIGN = {"confirmation_code": "123456"}


@pytest.fixture
async def approved(api: AsyncClient, session: AsyncSession, underwriter: User, draft: dict) -> str:
    await at_underwriter(session, draft["id"])
    response = await api.post(
        f"/api/v1/backoffice/applications/{draft['id']}/decision",
        json=APPROVE,
        headers=auth(underwriter),
    )
    assert response.status_code == 201, response.text
    return draft["id"]


async def contracts_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(LoanContract))


async def test_contract_is_prepared_on_accept(
    api: AsyncClient, session: AsyncSession, client_user: User, approved: str
) -> None:
    url = f"/api/v1/applications/{approved}"
    headers = auth(client_user)
    assert (await api.get(f"{url}/contract", headers=headers)).status_code == 404

    accepted = await api.post(f"{url}/offer/accept", headers=headers)
    assert accepted.json()["status"] == "e_sign"
    offer = (await api.get(f"{url}/offer", headers=headers)).json()

    contract = (await api.get(f"{url}/contract", headers=headers)).json()
    assert contract["contract_number"].startswith("КД-")
    assert contract["status"] == "awaiting_signature"
    assert contract["principal_amount"] == "3000000.00"
    assert contract["monthly_payment"] == offer["estimated_monthly_payment"]
    assert len(contract["schedule"]) == 36
    assert contract["loan_account_number"] is None
    assert contract["next_payment"] is None

    # Повторное принятие ничего не создаёт и не меняет
    again = await api.post(f"{url}/offer/accept", headers=headers)
    assert again.status_code == 200
    assert again.json()["status"] == "e_sign"
    assert await contracts_count(session) == 1


async def test_sign_disburses_and_is_idempotent(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    underwriter: User,
    approved: str,
) -> None:
    url = f"/api/v1/applications/{approved}"
    headers = auth(client_user)
    await api.post(f"{url}/offer/accept", headers=headers)

    signed = await api.post(f"{url}/sign", json=SIGN, headers=headers)
    assert signed.status_code == 200, signed.text
    body = signed.json()
    assert body["status"] == "completed"
    assert body["client_status"] == "disbursed"

    contract = (await api.get(f"{url}/contract", headers=headers)).json()
    assert contract["status"] == "active"
    assert contract["signature_id"].startswith("sig_")
    assert contract["loan_account_number"].startswith("45207810")
    assert len(contract["loan_account_number"]) == 20
    # Расчётный счёт - из профиля клиента в банке
    assert contract["settlement_account_number"] == "40702810770000000100"
    assert contract["disbursement_transaction_id"].startswith("txn_")
    assert contract["first_payment_date"] > date.today().isoformat()
    assert contract["next_payment"]["installment_no"] == 1
    assert contract["outstanding_balance"] == "3000000.00"

    again = await api.post(f"{url}/sign", json=SIGN, headers=headers)
    assert again.status_code == 200
    assert (await api.get(f"{url}/contract", headers=headers)).json() == contract
    assert await contracts_count(session) == 1
    items = await session.scalar(select(func.count()).select_from(PaymentScheduleItem))
    assert items == 36

    loans_list = (await api.get("/api/v1/loans", headers=headers)).json()
    assert [loan["id"] for loan in loans_list] == [contract["id"]]
    loan = (await api.get(f"/api/v1/loans/{contract['id']}", headers=headers)).json()
    assert loan["schedule"] == contract["schedule"]

    detail = (
        await api.get(f"/api/v1/backoffice/applications/{approved}", headers=auth(underwriter))
    ).json()
    assert detail["contract"]["contract_number"] == contract["contract_number"]


async def test_loans_are_private(
    api: AsyncClient, client_user: User, other_client: User, approved: str
) -> None:
    url = f"/api/v1/applications/{approved}"
    await api.post(f"{url}/offer/accept", headers=auth(client_user))
    contract = (await api.get(f"{url}/contract", headers=auth(client_user))).json()

    assert (await api.get("/api/v1/loans", headers=auth(other_client))).json() == []
    stranger = await api.get(f"/api/v1/loans/{contract['id']}", headers=auth(other_client))
    assert stranger.status_code == 404


async def test_sign_before_accept_and_after_reject(
    api: AsyncClient, client_user: User, approved: str
) -> None:
    url = f"/api/v1/applications/{approved}"
    headers = auth(client_user)
    early = await api.post(f"{url}/sign", json=SIGN, headers=headers)
    assert early.status_code == 409
    assert early.json()["detail"] == "Договор ещё не готов к подписанию"

    await api.post(f"{url}/offer/reject", json={}, headers=headers)
    assert (await api.post(f"{url}/sign", json=SIGN, headers=headers)).status_code == 409
    assert (await api.get(f"{url}/contract", headers=headers)).status_code == 404
    accept = await api.post(f"{url}/offer/accept", headers=headers)
    assert accept.status_code == 409


async def test_failed_disbursement_can_be_retried(
    api: AsyncClient,
    client_user: User,
    approved: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"/api/v1/applications/{approved}"
    headers = auth(client_user)
    await api.post(f"{url}/offer/accept", headers=headers)

    real_profile = loans.get_profile

    def without_account(inn: str):
        return real_profile(inn).model_copy(update={"bank_account": None})

    monkeypatch.setattr(loans, "get_profile", without_account)
    failed = await api.post(f"{url}/sign", json=SIGN, headers=headers)
    assert failed.status_code == 409
    assert "расчётного счёта" in failed.json()["detail"]
    # Подпись сохранилась, выдача ждёт повтора
    application = (await api.get(url, headers=headers)).json()
    assert application["status"] == "disbursement"
    assert application["available_actions"] == ["sign"]
    contract = (await api.get(f"{url}/contract", headers=headers)).json()
    assert contract["status"] == "signed"

    monkeypatch.setattr(loans, "get_profile", real_profile)
    retried = await api.post(f"{url}/sign", json=SIGN, headers=headers)
    assert retried.json()["status"] == "completed"
    assert (await api.get(f"{url}/contract", headers=headers)).json()["status"] == "active"


def test_schedule_amounts_match_offer_payment() -> None:
    assert loans.annuity_payment(Decimal("3000000"), 36, Decimal("18")) == Decimal("108457.19")
