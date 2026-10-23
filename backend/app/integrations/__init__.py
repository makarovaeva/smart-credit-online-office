"""Моки внешних источников. Данные - профили заёмщиков из датасета или запасного генератора."""

from app.integrations import bki, compliance, egrul, fns
from app.integrations.base import (
    CompanyNotFoundError,
    Fetcher,
    SourceUnavailableError,
    get_profile,
)
from app.integrations.synthetic import DEMO_SCENARIOS
from app.models.enums import CheckSource

SOURCES: dict[CheckSource, Fetcher] = {
    CheckSource.EGRUL: egrul.fetch,
    CheckSource.FNS: fns.fetch,
    CheckSource.BKI: bki.fetch,
    CheckSource.COMPLIANCE: compliance.fetch,
}

__all__ = [
    "DEMO_SCENARIOS",
    "SOURCES",
    "CompanyNotFoundError",
    "SourceUnavailableError",
    "get_profile",
]
