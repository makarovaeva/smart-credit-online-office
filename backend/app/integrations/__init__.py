"""Моки внешних источников. Синтетические данные, без сетевых вызовов."""

from app.integrations import bank_turnover, bki, egrul, fns, fssp
from app.integrations.base import Fetcher, SourceUnavailableError
from app.integrations.profiles import DEMO_SCENARIOS, CompanyNotFoundError
from app.models.enums import CheckSource

# Цифровой профиль пока не моделируется: его данные дублируют ФНС и ЕГРЮЛ
SOURCES: dict[CheckSource, Fetcher] = {
    CheckSource.EGRUL: egrul.fetch,
    CheckSource.FNS: fns.fetch,
    CheckSource.BKI: bki.fetch,
    CheckSource.FSSP: fssp.fetch,
    CheckSource.BANK_TURNOVER: bank_turnover.fetch,
}

__all__ = ["DEMO_SCENARIOS", "SOURCES", "CompanyNotFoundError", "SourceUnavailableError"]
