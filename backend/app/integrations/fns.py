"""Мок ФНС: отчётность за прошлый год, налоги, задолженность, приостановления операций
и признаки недостоверности (массовый адрес, массовый руководитель)."""

from datetime import date
from typing import Any

from app.integrations.base import load_profile, money
from app.models.enums import CheckSource


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    p = load_profile(CheckSource.FNS, inn, today)
    year = (today or date.today()).year - 1
    suspensions = []
    if p.blocked_115fz:
        suspensions.append({"reason": "115-fz", "description": "Блокировка по 115-ФЗ"})
    if p.blocked_by_tax:
        suspensions.append({"reason": "tax", "description": "Решение налогового органа"})
    return {
        "inn": p.inn,
        "report_year": year,
        "revenue": money(p.annual_revenue),
        "taxes_paid": money(p.taxes_paid),
        "tax_debt": money(p.tax_debt),
        "average_headcount": p.average_headcount,
        "account_suspensions": suspensions,
        "mass_address": p.mass_address,
        "mass_director": p.mass_director,
    }
