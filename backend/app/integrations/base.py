"""Общий контракт моков внешних источников."""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from app.integrations.dataset import BorrowerRecord, find_record
from app.integrations.synthetic import DEMO_UNAVAILABLE, NOT_FOUND_INNS, generate_record
from app.models.enums import CheckSource

# fetch(inn, today) -> сырой ответ источника (JSON-совместимый dict)
Fetcher = Callable[[str, date | None], Awaitable[dict[str, Any]]]


class SourceUnavailableError(Exception):
    """Источник не ответил - проверка сохраняется со статусом failed."""


class CompanyNotFoundError(Exception):
    pass


def get_record(inn: str, today: date | None = None) -> BorrowerRecord:
    """Запись из датасета ML, а если ИНН там нет - сгенерированная."""
    if inn in NOT_FOUND_INNS:
        raise CompanyNotFoundError(inn)
    return find_record(inn) or generate_record(inn, today or date.today())


def load_record(source: CheckSource, inn: str, today: date | None) -> BorrowerRecord:
    if source in DEMO_UNAVAILABLE.get(inn, ()):
        raise SourceUnavailableError(f"{source} не отвечает")
    return get_record(inn, today)
