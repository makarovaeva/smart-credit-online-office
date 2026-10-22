"""Мок БКИ: блок bki записи ML."""

from datetime import date
from typing import Any

from app.integrations.base import load_record
from app.models.enums import CheckSource


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    return load_record(CheckSource.BKI, inn, today).bki.model_dump(mode="json")
