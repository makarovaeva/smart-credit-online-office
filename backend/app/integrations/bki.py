"""Мок БКИ: bki_data профиля."""

from datetime import date
from typing import Any

from app.integrations.base import load_profile
from app.models.enums import CheckSource


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    profile = load_profile(CheckSource.BKI, inn, today)
    return profile.model_dump(mode="json", include={"bki_data"})
