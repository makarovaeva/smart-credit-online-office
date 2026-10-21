"""Мок оборотов по расчётному счёту в банке за 12 полных месяцев."""

from datetime import date
from typing import Any

from app.integrations.base import load_profile, money
from app.models.enums import CheckSource


def _month(today: date, months_back: int) -> str:
    total = today.year * 12 + today.month - 1 - months_back
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    p = load_profile(CheckSource.BANK_TURNOVER, inn, today)
    today = today or date.today()
    return {
        "inn": p.inn,
        "account": f"40702810{p.inn[-10:]}00",
        "months": [
            {"month": _month(today, 12 - i), "inflow": money(inflow), "outflow": money(outflow)}
            for i, (inflow, outflow) in enumerate(p.turnover)
        ],
    }
