"""Общий контракт моков внешних источников."""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from app.integrations.dataset import BorrowerProfile, find_profile
from app.integrations.synthetic import DEMO_UNAVAILABLE, NOT_FOUND_INNS, generate_profile
from app.models.enums import CheckSource

# fetch(inn, today) -> сырой ответ источника (JSON-совместимый dict)
Fetcher = Callable[[str, date | None], Awaitable[dict[str, Any]]]


class SourceUnavailableError(Exception):
    """Источник не ответил - проверка сохраняется со статусом failed."""


class CompanyNotFoundError(Exception):
    pass


def get_profile(inn: str, today: date | None = None) -> BorrowerProfile:
    """Профиль из датасета, а если ИНН там нет - сгенерированный."""
    if inn in NOT_FOUND_INNS:
        raise CompanyNotFoundError(inn)
    return find_profile(inn) or generate_profile(inn, today or date.today())


def load_profile(source: CheckSource, inn: str, today: date | None) -> BorrowerProfile:
    if source in DEMO_UNAVAILABLE.get(inn, ()):
        raise SourceUnavailableError(f"{source} не отвечает")
    return get_profile(inn, today)
