"""Мок ЕГРЮЛ/ЕГРИП: блок company записи ML."""

from datetime import date
from typing import Any

from app.integrations.base import load_record
from app.models.enums import CheckSource


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    return load_record(CheckSource.EGRUL, inn, today).company.model_dump(mode="json")
