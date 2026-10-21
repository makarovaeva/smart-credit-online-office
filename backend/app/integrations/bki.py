"""Мок БКИ: скоринговый балл (шкала 1-999), действующие кредиты, просрочки, запросы и отказы."""

from datetime import date
from typing import Any

from app.integrations.base import load_profile, money
from app.models.enums import CheckSource


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    p = load_profile(CheckSource.BKI, inn, today)
    return {
        "inn": p.inn,
        "score": p.bki_score,
        "score_scale": "1-999",
        "active_loans": [
            {
                "creditor": loan.creditor,
                "balance": money(loan.balance),
                "monthly_payment": money(loan.monthly_payment),
                "overdue_days": loan.overdue_days,
            }
            for loan in p.loans
        ],
        "overdue_30_plus_12m": p.overdue_30_plus_12m,
        "max_overdue_days_24m": p.max_overdue_days_24m,
        "inquiries_30d": p.inquiries_30d,
        "refusals_90d": p.refusals_90d,
    }
