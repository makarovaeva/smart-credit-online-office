"""Моки внешних источников. Данные - из датасета ML или запасного генератора, без сети."""

from app.integrations import bki, egrul, fns
from app.integrations.base import (
    CompanyNotFoundError,
    Fetcher,
    SourceUnavailableError,
    get_record,
)
from app.integrations.synthetic import DEMO_SCENARIOS
from app.models.enums import CheckSource

# ФССП, обороты РКО и цифровой профиль в формате ML пока нет
SOURCES: dict[CheckSource, Fetcher] = {
    CheckSource.EGRUL: egrul.fetch,
    CheckSource.FNS: fns.fetch,
    CheckSource.BKI: bki.fetch,
}

__all__ = [
    "DEMO_SCENARIOS",
    "SOURCES",
    "CompanyNotFoundError",
    "SourceUnavailableError",
    "get_record",
]
