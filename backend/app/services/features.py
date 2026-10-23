"""Признаки заёмщика из ответов внешних источников (блоки Borrower Profile).

Два потребителя: кредитная политика (RiskSignals) и ML-модель скоринга (плоский словарь values).
Числовые поля сверх формата профиля в financials и bki_data (например, балансовые показатели
генератора ML) попадают в values автоматически с префиксами fin_ и bki_.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.integrations import SOURCES
from app.models.enums import CheckSource, StopFactorCode
from app.services.credit_policy import RiskSignals

# Пороговые значения, которых нет в кредитной политике на доске, - допущения
WEAK_OVERDUE_DAYS = 30
# Расхождение анкеты клиента с источниками, при котором данные считаются конфликтующими
CONFLICT_TOLERANCE = Decimal("0.30")

SC = StopFactorCode


@dataclass(frozen=True)
class Features:
    signals: RiskSignals
    # Плоские признаки для ML: только числа, строки, bool
    values: dict[str, Any]
    # Годовые платежи по действующим кредитам из БКИ - вход DSCR
    existing_annual_debt_service: Decimal | None
    missing_sources: list[CheckSource]
    conflicts: list[str] = field(default_factory=list)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)


def _diverges(declared: Decimal | None, actual: Decimal | None) -> bool:
    if declared is None or actual is None or max(declared, actual) == 0:
        return False
    return abs(declared - actual) / max(declared, actual) > CONFLICT_TOLERANCE


def _ratio(numerator: Decimal, denominator: Decimal) -> float | None:
    return float(round(numerator / denominator, 4)) if denominator else None


def _extra_numbers(block: Mapping[str, Any], prefix: str, known: set[str]) -> dict[str, float]:
    return {
        f"{prefix}{key}": float(value)
        for key, value in block.items()
        if key not in known and isinstance(value, int | float) and not isinstance(value, bool)
    }


def _longest_negative_streak(cash_flow: list[Any]) -> int:
    streak = longest = 0
    for value in cash_flow:
        streak = streak + 1 if _dec(value) < 0 else 0
        longest = max(longest, streak)
    return longest


def _egrul(data: Mapping[str, Any], today: date) -> tuple[dict[str, Any], set[SC]]:
    company = data["company"]
    flags = {SC.NO_EMPLOYEES} if company["employees_count"] == 0 else set()
    values = {
        "legal_form": company["legal_form"].lower(),
        "okved_main": company["okved_main"]["code"],
        "region_code": company["region_code"],
        "tax_system": company.get("tax_system") or "unknown",
        "business_age_months": _months_between(
            date.fromisoformat(company["registration_date"]), today
        ),
        "employees_count": company["employees_count"],
        "owners_count": len(data.get("owners") or []),
    }
    return values, flags


def _fns(data: Mapping[str, Any]) -> tuple[dict[str, Any], set[SC]]:
    fns = data["fns_data"]
    checks = {
        SC.BANKRUPTCY: fns["bankruptcy_status"] == "bankruptcy",
        SC.OBSERVATION_PROCEDURE: fns["bankruptcy_status"] == "observation",
        SC.ACCOUNTS_BLOCKED_115FZ: fns["has_account_block_115fz"],
        SC.MASS_ADDRESS: fns["is_mass_address"],
        SC.MASS_DIRECTOR: fns["is_mass_director"],
        SC.NO_TAX_ACTIVITY: not fns["has_tax_activity"],
    }
    arrears = _dec(fns["tax_arrears_amount"])
    values = {
        "egrul_status": fns["egrul_status"],
        "bankruptcy_status": fns["bankruptcy_status"],
        "blocked_115fz": fns["has_account_block_115fz"],
        "mass_address": fns["is_mass_address"],
        "mass_director": fns["is_mass_director"],
        "has_tax_activity": fns["has_tax_activity"],
        "tax_arrears": float(arrears),
        "has_tax_debt": arrears > 0,
    }
    return values, {code for code, hit in checks.items() if hit}


def _financials(fin: Mapping[str, Any]) -> tuple[dict[str, Any], int, Decimal]:
    cash_flow = fin["cash_flow_last_12m"]
    streak = _longest_negative_streak(cash_flow)
    change = _dec(fin["revenue_change_pct"])
    known = {"annual_turnover", "revenue_change_pct", "ebitda", "cash_flow_last_12m"}
    values = {
        "fin_annual_turnover": float(_dec(fin["annual_turnover"])),
        "fin_ebitda": float(_dec(fin["ebitda"])),
        "fin_revenue_change_pct": float(change),
        "fin_cash_flow_12m": float(sum((_dec(v) for v in cash_flow), Decimal(0))),
        "negative_cash_flow_months": streak,
        **_extra_numbers(fin, "fin_", known),
    }
    # Падение выручки - доля 0..1, рост не учитывается
    return values, streak, max(Decimal(0), -change / 100)


def _bki(bki: Mapping[str, Any]) -> tuple[dict[str, Any], bool, Decimal]:
    overdue = _dec(bki["overdue_amount"])
    quality = bki["credit_history_quality"]
    weak = quality == "weak" or overdue > 0 or bki["max_overdue_days_12m"] >= WEAK_OVERDUE_DAYS
    known = {
        "active_loans_count",
        "total_debt_amount",
        "monthly_debt_service",
        "overdue_amount",
        "max_overdue_days_12m",
    }
    values = {
        "credit_history_quality": quality,
        "bki_active_loans": bki["active_loans_count"],
        "bki_total_debt": float(_dec(bki["total_debt_amount"])),
        "bki_monthly_debt_service": float(_dec(bki["monthly_debt_service"])),
        "bki_overdue_amount": float(overdue),
        "bki_max_overdue_days_12m": bki["max_overdue_days_12m"],
        "weak_credit_history": weak,
        **_extra_numbers(bki, "bki_", known),
    }
    return values, weak, _dec(bki["monthly_debt_service"]) * 12


def build_features(
    results: Mapping[CheckSource, Mapping[str, Any]],
    *,
    declared_revenue: Decimal | None = None,
    declared_monthly_debt_payments: Decimal | None = None,
    today: date | None = None,
) -> Features:
    """results - успешные ответы источников; недостающие попадают в missing_sources.
    Признаки отсутствующего источника не выставляются: что делать без них, решает конвейер."""
    today = today or date.today()
    values: dict[str, Any] = {}
    flags: set[SC] = set()
    conflicts: list[str] = []
    signal_args: dict[str, Any] = {}
    debt_service = None
    fin = bki = None

    if egrul := results.get(CheckSource.EGRUL):
        egrul_values, egrul_flags = _egrul(egrul, today)
        values |= egrul_values
        flags |= egrul_flags
        signal_args["business_age_months"] = egrul_values["business_age_months"]
    if fns := results.get(CheckSource.FNS):
        fns_values, fns_flags = _fns(fns)
        values |= fns_values
        flags |= fns_flags
        fin = fns["financials"]
        fin_values, streak, drop = _financials(fin)
        values |= fin_values
        signal_args |= {"negative_cash_flow_months": streak, "revenue_drop": drop}
        if _diverges(declared_revenue, _dec(fin["annual_turnover"])):
            conflicts.append("Выручка в анкете расходится с данными отчётности")
    if compliance := results.get(CheckSource.COMPLIANCE):
        data = compliance["compliance"]
        values |= {
            "sanctions_hit": data["sanctions_hit"],
            "prohibited_activity": data["is_prohibited_activity"],
        }
        if data["sanctions_hit"]:
            flags.add(SC.SANCTIONED_OWNER)
        if data["is_prohibited_activity"]:
            flags.add(SC.PROHIBITED_ACTIVITY)
    if bki_response := results.get(CheckSource.BKI):
        bki = bki_response["bki_data"]
        bki_values, weak, debt_service = _bki(bki)
        values |= bki_values
        signal_args["weak_credit_history"] = weak
        if _diverges(declared_monthly_debt_payments, debt_service / 12):
            conflicts.append("Платежи по кредитам в анкете расходятся с данными БКИ")

    if fin is not None:
        ebitda = _dec(fin["ebitda"])
        ratios = {
            "ebitda_margin": _ratio(ebitda, _dec(fin["annual_turnover"])),
            "debt_to_ebitda": _ratio(_dec(bki["total_debt_amount"]), ebitda) if bki else None,
            # DSCR по действующим кредитам, без запрашиваемого
            "dscr_existing": _ratio(ebitda, debt_service) if debt_service else None,
        }
        values |= {key: value for key, value in ratios.items() if value is not None}

    values["conflicting_data"] = bool(conflicts)
    missing = [source for source in SOURCES if source not in results]
    return Features(
        signals=RiskSignals(
            flags=frozenset(flags),
            conflicting_data=bool(conflicts),
            missing_data=bool(missing),
            **signal_args,
        ),
        values=values,
        existing_annual_debt_service=debt_service,
        missing_sources=missing,
        conflicts=conflicts,
    )
