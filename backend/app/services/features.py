"""Признаки заёмщика из ответов внешних источников (формат записи генератора ML).

Два потребителя: кредитная политика (RiskSignals) и ML-модель скоринга (плоский словарь values).
Поля вне базового формата ML (санкции, 115-ФЗ, массовость, скор БКИ...) необязательны:
если генератор начнёт их отдавать, соответствующие сигналы включатся сами.
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
WEAK_BKI_SCORE = 600
FREQUENT_REFUSALS_90D = 3
# Расхождение между источниками, при котором данные считаются конфликтующими
CONFLICT_TOLERANCE = Decimal("0.30")
# Азартные игры
PROHIBITED_OKVED_PREFIXES = ("92.",)


@dataclass(frozen=True)
class Features:
    signals: RiskSignals
    # Плоские признаки для ML: только числа, строки, bool
    values: dict[str, Any]
    # Годовые платежи по действующим кредитам из отчётности - вход DSCR и Debt Burden
    existing_annual_debt_service: Decimal | None
    missing_sources: list[CheckSource]
    conflicts: list[str] = field(default_factory=list)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)


def _diverges(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None or max(a, b) == 0:
        return False
    return abs(a - b) / max(a, b) > CONFLICT_TOLERANCE


def _ratio(numerator: Decimal, denominator: Decimal) -> float | None:
    return float(round(numerator / denominator, 4)) if denominator else None


def _company(data: Mapping[str, Any], today: date) -> tuple[dict[str, Any], set[StopFactorCode]]:
    flags = set()
    okved = data["okved_main"]
    if okved.startswith(PROHIBITED_OKVED_PREFIXES):
        flags.add(StopFactorCode.PROHIBITED_ACTIVITY)
    if data["employees_count"] == 0:
        flags.add(StopFactorCode.NO_EMPLOYEES)
    if data.get("status") == "bankruptcy":
        flags.add(StopFactorCode.BANKRUPTCY)
    if any(f.get("sanctions_match") for f in data.get("founders", [])):
        flags.add(StopFactorCode.SANCTIONED_OWNER)
    values = {
        "legal_form": data["legal_form"].lower(),
        "okved_main": okved,
        "region_code": data["region_code"],
        "business_age_months": _months_between(
            date.fromisoformat(data["registration_date"]), today
        ),
        "employees_count": data["employees_count"],
        "prohibited_activity": StopFactorCode.PROHIBITED_ACTIVITY in flags,
    }
    return values, flags


def _fns(data: Mapping[str, Any]) -> tuple[dict[str, Any], set[StopFactorCode]]:
    flags = set()
    income = _dec(data["annual_income_rub"])
    # Недействующую компанию (банкротство, ликвидация) трактуем как стоп-фактор банкротства
    if not data["is_active"]:
        flags.add(StopFactorCode.BANKRUPTCY)
    if income == 0:
        flags.add(StopFactorCode.NO_TAX_ACTIVITY)
    for key, code in (
        ("blocked_115fz", StopFactorCode.ACCOUNTS_BLOCKED_115FZ),
        ("mass_address", StopFactorCode.MASS_ADDRESS),
        ("mass_director", StopFactorCode.MASS_DIRECTOR),
    ):
        if data.get(key):
            flags.add(code)
    tax_debt = _dec(data["tax_debt_rub"])
    values = {
        "fns_is_active": data["is_active"],
        "sme_category": data["sme_category"],
        "fns_annual_income": float(income),
        "fns_tax_debt": float(tax_debt),
        "has_tax_debt": tax_debt > 0,
    }
    return values, flags


def _financials(data: Mapping[str, Any]) -> dict[str, Any]:
    revenue = _dec(data["revenue_rub"])
    ebitda = _dec(data["ebitda_rub"])
    debt = _dec(data["total_debt_rub"])
    debt_service = _dec(data["annual_debt_service_rub"])
    values = {
        f"fin_{key.removesuffix('_rub')}": float(_dec(data[key]))
        for key in (
            "revenue_rub",
            "operating_costs_rub",
            "ebitda_rub",
            "cfads_rub",
            "total_debt_rub",
            "annual_debt_service_rub",
            "assets_rub",
            "liabilities_rub",
            "equity_rub",
        )
    }
    ratios = {
        "ebitda_margin": _ratio(ebitda, revenue),
        "debt_to_ebitda": _ratio(debt, ebitda),
        "equity_ratio": _ratio(_dec(data["equity_rub"]), _dec(data["assets_rub"])),
        # DSCR по действующим кредитам, без запрашиваемого
        "dscr_existing": _ratio(ebitda, debt_service),
    }
    return values | {key: value for key, value in ratios.items() if value is not None}


def _bki(data: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    overdue_debt = _dec(data["overdue_debt_rub"])
    score = data.get("score")
    weak = (
        overdue_debt > 0
        or data["max_overdue_days"] >= WEAK_OVERDUE_DAYS
        or (score is not None and score < WEAK_BKI_SCORE)
        or data.get("overdue_30_plus_12m", 0) > 0
        or data.get("refusals_90d", 0) >= FREQUENT_REFUSALS_90D
    )
    values = {
        "bki_active_loans": data["active_loans"],
        "bki_outstanding_debt": float(_dec(data["outstanding_debt_rub"])),
        "bki_overdue_debt": float(overdue_debt),
        "bki_max_overdue_days": data["max_overdue_days"],
        "bki_credit_history_months": data["credit_history_months"],
        "weak_credit_history": weak,
    }
    if score is not None:
        values["bki_score"] = score
    return values, weak


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
    flags: set[StopFactorCode] = set()
    conflicts: list[str] = []
    signal_args: dict[str, Any] = {}
    debt_service = None
    fin = None

    if company := results.get(CheckSource.EGRUL):
        company_values, company_flags = _company(company, today)
        values |= company_values
        flags |= company_flags
        signal_args["business_age_months"] = company_values["business_age_months"]
    if fns := results.get(CheckSource.FNS):
        fns_values, fns_flags = _fns(fns)
        values |= fns_values
        flags |= fns_flags
        income = _dec(fns["annual_income_rub"])
        if fin := fns.get("financials"):
            values |= _financials(fin)
            debt_service = _dec(fin["annual_debt_service_rub"])
            if _diverges(_dec(fin["revenue_rub"]), income):
                conflicts.append("Выручка в отчётности расходится с доходами в ФНС")
        if _diverges(declared_revenue, income):
            conflicts.append("Выручка в анкете расходится с данными ФНС")
        if debt_service is not None and _diverges(
            declared_monthly_debt_payments, debt_service / 12
        ):
            conflicts.append("Платежи по кредитам в анкете расходятся с отчётностью")
    if bki := results.get(CheckSource.BKI):
        bki_values, weak = _bki(bki)
        values |= bki_values
        signal_args["weak_credit_history"] = weak
        if fin and _diverges(_dec(fin["total_debt_rub"]), _dec(bki["outstanding_debt_rub"])):
            conflicts.append("Долг в отчётности расходится с данными БКИ")

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
