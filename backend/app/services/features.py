"""Признаки заёмщика из ответов внешних источников.

Два потребителя: кредитная политика (RiskSignals) и ML-модель скоринга (плоский словарь values).
Список ML-признаков от команды ML пока не согласован - сейчас это всё, что нужно политике,
плюс сырые показатели источников. Новые признаки добавляются здесь, моки менять не нужно.
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
WEAK_BKI_SCORE = 600
FREQUENT_REFUSALS_90D = 3
# Расхождение данных анкеты с источниками, при котором данные считаются конфликтующими
CONFLICT_TOLERANCE = Decimal("0.30")
# Азартные игры
PROHIBITED_OKVED_PREFIXES = ("92.",)

ZERO = Decimal("0")


@dataclass(frozen=True)
class Features:
    signals: RiskSignals
    # Плоские признаки для ML: только числа, строки, bool и None
    values: dict[str, Any]
    # Годовые платежи по действующим кредитам по данным БКИ - вход DSCR и Debt Burden
    existing_annual_debt_service: Decimal | None
    missing_sources: list[CheckSource]
    conflicts: list[str] = field(default_factory=list)


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)


def _diverges(declared: Decimal | None, actual: Decimal | None) -> bool:
    if declared is None or actual is None or actual == 0:
        return False
    return abs(declared - actual) / actual > CONFLICT_TOLERANCE


def _egrul(data: Mapping[str, Any], today: date) -> tuple[dict[str, Any], set[StopFactorCode]]:
    flags = set()
    okved = data["okved_main"]["code"]
    founders = data["founders"]
    if data["status"]["code"] == "bankruptcy":
        flags.add(StopFactorCode.BANKRUPTCY)
    if any(f["sanctions_match"] for f in founders):
        flags.add(StopFactorCode.SANCTIONED_OWNER)
    if okved.startswith(PROHIBITED_OKVED_PREFIXES):
        flags.add(StopFactorCode.PROHIBITED_ACTIVITY)
    values = {
        "legal_form": data["legal_form"],
        "okved_main": okved,
        "region": data["region"],
        "business_age_months": _months_between(
            date.fromisoformat(data["registration_date"]), today
        ),
        "egrul_status": data["status"]["code"],
        "founders_count": len(founders),
        "has_sanctioned_founder": StopFactorCode.SANCTIONED_OWNER in flags,
        "prohibited_activity": StopFactorCode.PROHIBITED_ACTIVITY in flags,
    }
    return values, flags


def _fns(data: Mapping[str, Any]) -> tuple[dict[str, Any], set[StopFactorCode]]:
    flags = set()
    reasons = {s["reason"] for s in data["account_suspensions"]}
    taxes_paid = Decimal(data["taxes_paid"])
    if "115-fz" in reasons:
        flags.add(StopFactorCode.ACCOUNTS_BLOCKED_115FZ)
    if data["mass_address"]:
        flags.add(StopFactorCode.MASS_ADDRESS)
    if data["mass_director"]:
        flags.add(StopFactorCode.MASS_DIRECTOR)
    if data["average_headcount"] == 0:
        flags.add(StopFactorCode.NO_EMPLOYEES)
    if taxes_paid == 0:
        flags.add(StopFactorCode.NO_TAX_ACTIVITY)
    values = {
        "fns_revenue": float(Decimal(data["revenue"])),
        "fns_taxes_paid": float(taxes_paid),
        "fns_tax_debt": float(Decimal(data["tax_debt"])),
        "fns_average_headcount": data["average_headcount"],
        "blocked_115fz": "115-fz" in reasons,
        "blocked_by_tax": "tax" in reasons,
        "mass_address": data["mass_address"],
        "mass_director": data["mass_director"],
    }
    return values, flags


def _bki(data: Mapping[str, Any]) -> tuple[dict[str, Any], bool, Decimal]:
    loans = data["active_loans"]
    monthly = sum((Decimal(loan["monthly_payment"]) for loan in loans), ZERO)
    weak = (
        data["score"] < WEAK_BKI_SCORE
        or data["overdue_30_plus_12m"] > 0
        or data["refusals_90d"] >= FREQUENT_REFUSALS_90D
        or any(loan["overdue_days"] > 0 for loan in loans)
    )
    values = {
        "bki_score": data["score"],
        "bki_active_loans": len(loans),
        "bki_total_debt": float(sum((Decimal(loan["balance"]) for loan in loans), ZERO)),
        "bki_monthly_payments": float(monthly),
        "bki_current_overdue": any(loan["overdue_days"] > 0 for loan in loans),
        "bki_overdue_30_plus_12m": data["overdue_30_plus_12m"],
        "bki_max_overdue_days_24m": data["max_overdue_days_24m"],
        "bki_inquiries_30d": data["inquiries_30d"],
        "bki_refusals_90d": data["refusals_90d"],
        "weak_credit_history": weak,
    }
    return values, weak, monthly * 12


def _fssp(data: Mapping[str, Any]) -> dict[str, Any]:
    proceedings = data["proceedings"]
    return {
        "fssp_open_proceedings": len(proceedings),
        "fssp_total_amount": float(sum((Decimal(p["amount"]) for p in proceedings), ZERO)),
    }


def _turnover(data: Mapping[str, Any]) -> tuple[dict[str, Any], int, Decimal]:
    months = data["months"]
    inflows = [Decimal(m["inflow"]) for m in months]
    flows = [Decimal(m["inflow"]) - Decimal(m["outflow"]) for m in months]

    streak = longest = 0
    for flow in flows:
        streak = streak + 1 if flow < 0 else 0
        longest = max(longest, streak)
    # Падение: последние 6 месяцев к предыдущим 6 (как «падение оборота на 25% за 6 месяцев»)
    previous, recent = sum(inflows[:-6], ZERO), sum(inflows[-6:], ZERO)
    drop = max(ZERO, (previous - recent) / previous) if previous > 0 else ZERO
    values = {
        "turnover_inflow_12m": float(sum(inflows, ZERO)),
        "turnover_avg_monthly_inflow": float(sum(inflows, ZERO) / len(inflows)) if inflows else 0.0,
        "turnover_net_cash_flow_12m": float(sum(flows, ZERO)),
        "negative_cash_flow_months": longest,
        "revenue_drop_6m": float(round(drop, 4)),
    }
    return values, longest, drop


def build_features(
    results: Mapping[CheckSource, Mapping[str, Any]],
    *,
    declared_revenue: Decimal | None = None,
    declared_monthly_debt_payments: Decimal | None = None,
    today: date | None = None,
) -> Features:
    """results - успешные ответы источников; недостающие попадают в missing_sources.
    Признаки отсутствующего источника не выставляются: решение, что делать без них,
    принимает конвейер."""
    today = today or date.today()
    values: dict[str, Any] = {}
    flags: set[StopFactorCode] = set()
    conflicts: list[str] = []
    signal_args: dict[str, Any] = {}
    debt_service = None

    if egrul := results.get(CheckSource.EGRUL):
        egrul_values, egrul_flags = _egrul(egrul, today)
        values |= egrul_values
        flags |= egrul_flags
        signal_args["business_age_months"] = egrul_values["business_age_months"]
    if fns := results.get(CheckSource.FNS):
        fns_values, fns_flags = _fns(fns)
        values |= fns_values
        flags |= fns_flags
        if _diverges(declared_revenue, Decimal(fns["revenue"])):
            conflicts.append("Выручка в анкете расходится с отчётностью в ФНС")
    if bki := results.get(CheckSource.BKI):
        bki_values, weak, debt_service = _bki(bki)
        values |= bki_values
        signal_args["weak_credit_history"] = weak
        if _diverges(declared_monthly_debt_payments, debt_service / 12):
            conflicts.append("Платежи по кредитам в анкете расходятся с данными БКИ")
    if fssp := results.get(CheckSource.FSSP):
        values |= _fssp(fssp)
    if turnover := results.get(CheckSource.BANK_TURNOVER):
        turnover_values, streak, drop = _turnover(turnover)
        values |= turnover_values
        signal_args |= {"negative_cash_flow_months": streak, "revenue_drop": drop}
        # Обороты меньше выручки - норма (есть счета в других банках), больше - нет
        inflow = Decimal(str(turnover_values["turnover_inflow_12m"]))
        if fns and inflow > Decimal(fns["revenue"]) * (1 + CONFLICT_TOLERANCE):
            conflicts.append("Обороты по счёту заметно больше выручки в отчётности ФНС")

    values["conflicting_data"] = bool(conflicts)
    return Features(
        signals=RiskSignals(
            flags=frozenset(flags), conflicting_data=bool(conflicts), **signal_args
        ),
        values=values,
        existing_annual_debt_service=debt_service,
        missing_sources=[source for source in SOURCES if source not in results],
        conflicts=conflicts,
    )
