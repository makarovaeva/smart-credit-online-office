"""График платежей по кредиту.

Упрощения проекта: аннуитет, проценты за месяц = остаток × годовая ставка / 12 (без учёта числа
дней), платежи в тот же день месяца, что и выдача. Последний платёж закрывает остаток копейка
в копейку. Платёж совпадает с «ориентировочным платежом» в оффере.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.services.credit_policy import monthly_payment

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Installment:
    installment_no: int
    due_date: date
    principal_amount: Decimal
    interest_amount: Decimal
    total_amount: Decimal
    balance_after: Decimal


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def add_months(start: date, months: int) -> date:
    """Тот же день через N месяцев; 31-е в коротком месяце - последний день месяца."""
    total = start.year * 12 + start.month - 1 + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def annuity_payment(amount: Decimal, term_months: int, rate: Decimal) -> Decimal:
    return _money(monthly_payment(amount, term_months, rate))


def annuity_schedule(
    amount: Decimal, term_months: int, rate: Decimal, start: date
) -> list[Installment]:
    payment = annuity_payment(amount, term_months, rate)
    monthly_rate = rate / Decimal(1200)
    balance = amount
    schedule = []
    for no in range(1, term_months + 1):
        interest = _money(balance * monthly_rate)
        principal = balance if no == term_months else payment - interest
        balance -= principal
        schedule.append(
            Installment(
                installment_no=no,
                due_date=add_months(start, no),
                principal_amount=principal,
                interest_amount=interest,
                total_amount=principal + interest,
                balance_after=balance,
            )
        )
    return schedule
