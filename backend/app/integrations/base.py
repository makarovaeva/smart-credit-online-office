"""Общий контракт моков внешних источников."""

from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

from app.integrations.profiles import CompanyProfile, get_profile
from app.models.enums import CheckSource

# fetch(inn, today) -> сырой ответ источника (JSON-совместимый dict)
Fetcher = Callable[[str, date | None], Awaitable[dict[str, Any]]]


class SourceUnavailableError(Exception):
    """Источник не ответил - проверка сохраняется со статусом failed."""


def money(value: Decimal) -> str:
    """Деньги в ответах - строкой, как в API."""
    return f"{value:.2f}"


def load_profile(source: CheckSource, inn: str, today: date | None) -> CompanyProfile:
    profile = get_profile(inn, today)
    if source in profile.unavailable:
        raise SourceUnavailableError(f"{source} не отвечает")
    return profile
