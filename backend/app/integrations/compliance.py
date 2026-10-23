"""Мок комплаенс-проверки: санкционные списки и запрещённая деятельность (compliance профиля)."""

from datetime import date
from typing import Any

from app.integrations.base import load_profile
from app.models.enums import CheckSource


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    profile = load_profile(CheckSource.COMPLIANCE, inn, today)
    return profile.model_dump(mode="json", include={"compliance"})
