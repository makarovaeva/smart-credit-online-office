from datetime import date
from decimal import Decimal

from app.services.schedule import add_months, annuity_payment, annuity_schedule

D = Decimal


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 31), 2) == date(2026, 3, 31)
    assert add_months(date(2027, 1, 31), 13) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 15), 2) == date(2027, 1, 15)


def test_annuity_schedule_closes_the_loan() -> None:
    schedule = annuity_schedule(D("3000000"), 36, D("18"), date(2026, 10, 23))
    payment = annuity_payment(D("3000000"), 36, D("18"))

    assert payment == D("108457.19")
    assert len(schedule) == 36
    assert schedule[0].interest_amount == D("45000.00")
    assert schedule[0].due_date == date(2026, 11, 23)
    assert schedule[-1].due_date == date(2029, 10, 23)
    assert all(item.total_amount == payment for item in schedule[:-1])
    # Последний платёж закрывает остаток копейка в копейку
    assert abs(schedule[-1].total_amount - payment) < D("1")
    assert schedule[-1].balance_after == 0
    assert sum(item.principal_amount for item in schedule) == D("3000000")
    for prev, item in zip(schedule, schedule[1:], strict=False):
        assert item.balance_after == prev.balance_after - item.principal_amount
