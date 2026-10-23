"""Кредитный договор, график платежей и симуляция выдачи средств.

Все операции идемпотентны: договор и ссудный счёт создаются один раз (уникальность в БД),
повторный вызов возвращает уже созданное и не меняет данные.
"""

import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import CompanyNotFoundError, get_profile
from app.models import (
    Application,
    Company,
    CompanyMember,
    CreditDecision,
    LoanContract,
    PaymentScheduleItem,
    User,
)
from app.models.enums import LoanContractStatus, PaymentStatus
from app.models.loan import contract_number_seq
from app.schemas.loan import LoanContractRead, LoanShort, PaymentScheduleItemRead
from app.services.errors import ConflictError, NotFoundError
from app.services.schedule import add_months, annuity_payment, annuity_schedule

# Ссудный счёт юрлица (балансовый 452) в рублях (810)
LOAN_ACCOUNT_PREFIX = "45207810"


async def get_contract(session: AsyncSession, application_id: uuid.UUID) -> LoanContract | None:
    return await session.scalar(
        select(LoanContract).where(LoanContract.application_id == application_id)
    )


async def prepare_contract(
    session: AsyncSession, application: Application, decision: CreditDecision
) -> LoanContract:
    """Договор на условиях принятого оффера и график с плановыми датами (от сегодняшнего дня;
    при выдаче даты пересчитываются от фактической даты). Повторный вызов вернёт тот же договор."""
    if contract := await get_contract(session, application.id):
        return contract
    assert decision.approved_amount and decision.approved_term_months and decision.interest_rate
    number = await session.scalar(select(contract_number_seq.next_value()))
    start = date.today()
    schedule = annuity_schedule(
        decision.approved_amount, decision.approved_term_months, decision.interest_rate, start
    )
    contract = LoanContract(
        application_id=application.id,
        credit_decision_id=decision.id,
        contract_number=f"КД-{start.year}-{number:06d}",
        principal_amount=decision.approved_amount,
        term_months=decision.approved_term_months,
        interest_rate=decision.interest_rate,
        monthly_payment=annuity_payment(
            decision.approved_amount, decision.approved_term_months, decision.interest_rate
        ),
        first_payment_date=schedule[0].due_date,
        maturity_date=schedule[-1].due_date,
    )
    session.add(contract)
    await session.flush()
    session.add_all(
        PaymentScheduleItem(contract_id=contract.id, **asdict(item)) for item in schedule
    )
    await session.flush()
    return contract


def sign_contract(contract: LoanContract) -> None:
    """Симуляция электронной подписи."""
    if contract.signed_at is not None:
        return
    contract.signed_at = datetime.now(UTC)
    contract.signature_id = f"sig_{uuid.uuid4().hex[:20]}"
    contract.status = LoanContractStatus.SIGNED


async def _settlement_account(session: AsyncSession, application: Application) -> str:
    company = await session.get(Company, application.company_id)
    assert company is not None
    try:
        account = get_profile(company.inn).bank_account
    except CompanyNotFoundError:
        account = None
    number = (account or {}).get("account_number")
    if not number or (account or {}).get("status", "active") != "active":
        raise ConflictError("У клиента нет действующего расчётного счёта для зачисления")
    return number


async def disburse(session: AsyncSession, application: Application, contract: LoanContract) -> None:
    """Симуляция выдачи: открытие ссудного счёта и зачисление на расчётный счёт клиента.
    График пересчитывается от фактической даты выдачи. Повторный вызов ничего не меняет."""
    if contract.disbursed_at is not None:
        return
    if contract.signed_at is None:
        raise ConflictError("Договор не подписан")
    settlement = await _settlement_account(session, application)
    number = int(contract.contract_number.rsplit("-", 1)[1])
    now = datetime.now(UTC)

    contract.loan_account_number = f"{LOAN_ACCOUNT_PREFIX}{number:012d}"
    contract.settlement_account_number = settlement
    contract.disbursed_at = now
    contract.disbursement_transaction_id = f"txn_{uuid.uuid4().hex[:20]}"
    contract.status = LoanContractStatus.ACTIVE

    disbursed_on = now.date()
    for item in await _schedule(session, contract.id):
        item.due_date = add_months(disbursed_on, item.installment_no)
    contract.first_payment_date = add_months(disbursed_on, 1)
    contract.maturity_date = add_months(disbursed_on, contract.term_months)
    await session.flush()


async def _schedule(session: AsyncSession, contract_id: uuid.UUID) -> list[PaymentScheduleItem]:
    items = await session.scalars(
        select(PaymentScheduleItem)
        .where(PaymentScheduleItem.contract_id == contract_id)
        .order_by(PaymentScheduleItem.installment_no)
    )
    return list(items)


def _columns(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in type(obj).__mapper__.column_attrs}


def _summary(contract: LoanContract, schedule: list[PaymentScheduleItem]) -> dict:
    unpaid = [item for item in schedule if item.status != PaymentStatus.PAID]
    paid_principal = sum(
        (item.principal_amount for item in schedule if item.status == PaymentStatus.PAID),
        start=Decimal(0),
    )
    return {
        "outstanding_balance": contract.principal_amount - paid_principal,
        # До выдачи платить нечего
        "next_payment": (
            PaymentScheduleItemRead.model_validate(unpaid[0])
            if unpaid and contract.disbursed_at
            else None
        ),
    }


async def to_contract_read(session: AsyncSession, contract: LoanContract) -> LoanContractRead:
    schedule = await _schedule(session, contract.id)
    return LoanContractRead.model_validate(
        _columns(contract)
        | _summary(contract, schedule)
        | {"schedule": [PaymentScheduleItemRead.model_validate(i) for i in schedule]}
    )


def _client_contracts(user: User):
    companies = select(CompanyMember.company_id).where(CompanyMember.user_id == user.id)
    return (
        select(LoanContract)
        .join(Application, Application.id == LoanContract.application_id)
        .where(Application.company_id.in_(companies))
    )


async def list_loans(session: AsyncSession, user: User) -> list[LoanShort]:
    """Кредиты клиента: выданные и ожидающие подписания, новые первыми."""
    contracts = await session.scalars(
        _client_contracts(user).order_by(LoanContract.created_at.desc())
    )
    return [
        LoanShort.model_validate(_columns(c) | _summary(c, await _schedule(session, c.id)))
        for c in contracts
    ]


async def get_loan(session: AsyncSession, user: User, contract_id: uuid.UUID) -> LoanContractRead:
    contract = await session.scalar(_client_contracts(user).where(LoanContract.id == contract_id))
    if contract is None:
        raise NotFoundError("Кредит не найден")
    return await to_contract_read(session, contract)
