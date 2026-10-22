"""Мок ФНС: блок fns записи ML и бухгалтерская отчётность (financials), которую банк получает
через ФНС."""

from datetime import date
from typing import Any

from app.integrations.base import load_record
from app.models.enums import CheckSource


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    record = load_record(CheckSource.FNS, inn, today)
    return record.fns.model_dump(mode="json") | {
        "financials": record.financials.model_dump(mode="json")
    }
