"""Мок ФССП: открытые исполнительные производства."""

from datetime import date
from typing import Any

from app.integrations.base import load_profile, money
from app.models.enums import CheckSource


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    p = load_profile(CheckSource.FSSP, inn, today)
    return {
        "inn": p.inn,
        "proceedings": [
            {
                "number": item.number,
                "subject": item.subject,
                "amount": money(item.amount),
                "opened_at": item.opened_at.isoformat(),
            }
            for item in p.proceedings
        ],
    }
