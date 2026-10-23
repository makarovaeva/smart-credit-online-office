"""Semantic data-quality checks for the synthetic MMB credit-conveyor dataset.

Input: JSON arrays of Borrower Profile, Loan Application, Credit Assessment.
No calls to live FNS/BKI services, and no real credit-risk validation.
Pydantic schemas (once implemented in backend) should be run separately.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class Issue:
    level: str                  # "error" or "warning"
    path: str                   # e.g. assessments[0].metrics.dscr
    message: str


@dataclass
class QualityReport:
    counts: dict[str, int] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    def add(self, level: str, path: str, message: str) -> None:
        self.issues.append(Issue(level, path, message))

    @property
    def passed(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "counts": self.counts,
            "errors": sum(i.level == "error" for i in self.issues),
            "warnings": sum(i.level == "warning" for i in self.issues),
            "issues": [asdict(i) for i in self.issues],
        }


def get(obj: Any, *keys: str) -> Any:
    """Safely access a nested field; absent fields return None."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def number(value: Any) -> bool:
    """Reject booleans, strings, NaN and infinity as numeric values."""
    return type(value) in (int, float) and math.isfinite(value)


def require_number(report: QualityReport, path: str, value: Any,
                   minimum: float | None = None) -> bool:
    if not number(value):
        report.add("error", path, "Expected a finite numeric value")
        return False
    if minimum is not None and value < minimum:
        report.add("error", path, f"Must be >= {minimum}")
        return False
    return True


def parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def approx(report: QualityReport, path: str, actual: Any,
           expected: float, tolerance: float = 0.02) -> None:
    if require_number(report, path, actual) and not math.isclose(
        actual, expected, abs_tol=tolerance, rel_tol=1e-8
    ):
        report.add("error", path, f"Expected {expected:.4f}, received {actual}")


def longest_negative_streak(values: list[float]) -> int:
    """Longest consecutive run of strictly negative monthly cash flows."""
    best = current = 0
    for value in values:
        current = current + 1 if value < 0 else 0
        best = max(best, current)
    return best


def check_profile(profile: dict[str, Any], report: QualityReport,
                  path: str) -> None:
    company = get(profile, "company")
    financials = get(profile, "financials")
    bki = get(profile, "bki_data")
    if not all(isinstance(x, dict) for x in (company, financials, bki)):
        report.add("error", path, "company, financials and bki_data must be objects")
        return

    if get(company, "legal_form") not in {"ooo", "ip"}:
        report.add("error", f"{path}.company.legal_form", "Expected 'ooo' or 'ip'")
    if not isinstance(get(company, "inn"), str):
        report.add("error", f"{path}.company.inn", "INN must be a string")
    workers = get(company, "employees_count")
    if type(workers) is not int or workers < 0:
        report.add("error", f"{path}.company.employees_count", "Expected a nonnegative integer")

    registered = parse_date(get(company, "registration_date"))
    as_of = parse_date(get(financials, "as_of_date"))
    if registered is None or as_of is None:
        report.add("error", f"{path}.financials.as_of_date", "Expected valid registration and financial dates")
    elif registered > as_of:
        report.add("error", f"{path}.financials.as_of_date", "Financial data predates business registration")

    require_number(report, f"{path}.financials.annual_turnover",
                   get(financials, "annual_turnover"), minimum=0)
    require_number(report, f"{path}.financials.ebitda", get(financials, "ebitda"))
    flows = get(financials, "cash_flow_last_12m")
    if not isinstance(flows, list) or len(flows) != 12 or not all(number(x) for x in flows):
        report.add("error", f"{path}.financials.cash_flow_last_12m",
                   "Expected exactly 12 finite monthly cash flows")
    period = get(financials, "cash_flow_period_end")
    if not isinstance(period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        report.add("error", f"{path}.financials.cash_flow_period_end", "Expected YYYY-MM")
    elif as_of is not None and period > as_of.strftime("%Y-%m"):
        report.add("error", f"{path}.financials.cash_flow_period_end", "Cash flows extend beyond as_of_date")

    for field_name in ("active_loans_count", "total_debt_amount",
                       "monthly_debt_service", "overdue_amount", "max_overdue_days_12m"):
        require_number(report, f"{path}.bki_data.{field_name}",
                       get(bki, field_name), minimum=0)
    debt, overdue = get(bki, "total_debt_amount"), get(bki, "overdue_amount")
    if number(debt) and number(overdue) and overdue > debt:
        report.add("error", f"{path}.bki_data.overdue_amount", "Overdue amount exceeds total debt")


def check_application(app: dict[str, Any], known_borrowers: set[str],
                      report: QualityReport, path: str) -> None:
    borrower_id = get(app, "borrower_id")
    if not isinstance(borrower_id, str) or borrower_id not in known_borrowers:
        report.add("error", f"{path}.borrower_id", "Unknown borrower_id")
    require_number(report, f"{path}.loan_request.amount",
                   get(app, "loan_request", "amount"), minimum=0.01)
    term = get(app, "loan_request", "term_months")
    if type(term) is not int or term <= 0:
        report.add("error", f"{path}.loan_request.term_months", "Expected positive integer")
    collateral_type = get(app, "collateral", "type")
    collateral_value = get(app, "collateral", "market_value")
    if collateral_type == "none" and collateral_value is not None:
        report.add("error", f"{path}.collateral.market_value", "Unsecured loan should have null market_value")
    elif collateral_value is not None:
        require_number(report, f"{path}.collateral.market_value", collateral_value, minimum=0)


def check_assessment(assessment: dict[str, Any], known_applications: set[str],
                     report: QualityReport, path: str) -> None:
    app_id = get(assessment, "application_id")
    if not isinstance(app_id, str) or app_id not in known_applications:
        report.add("error", f"{path}.application_id", "Unknown application_id")
    inputs = get(assessment, "inputs")
    metrics = get(assessment, "metrics")
    if not isinstance(inputs, dict) or not isinstance(metrics, dict):
        report.add("error", path, "Expected objects 'inputs' and 'metrics'")
        return

    existing = get(inputs, "existing_debt_service_12m")
    new = get(inputs, "new_debt_service_12m")
    total = get(inputs, "total_future_debt_service")
    ebitda = get(inputs, "ebitda")
    for name, value in (("existing_debt_service_12m", existing),
                        ("new_debt_service_12m", new),
                        ("total_future_debt_service", total)):
        require_number(report, f"{path}.inputs.{name}", value, minimum=0)
    if number(existing) and number(new):
        approx(report, f"{path}.inputs.total_future_debt_service", total, existing + new, 1.01)

    if number(total) and total > 0 and number(ebitda):
        approx(report, f"{path}.metrics.dscr", get(metrics, "dscr"), ebitda / total)
    elif number(total) and total == 0:
        if get(metrics, "dscr") is not None:
            report.add("error", f"{path}.metrics.dscr", "Undefined for zero debt service; use null")
        report.add("warning", f"{path}.metrics.dscr", "Zero denominator: API contract needs a null policy")
    else:
        report.add("error", f"{path}.inputs.ebitda", "Cannot validate DSCR without numeric inputs")

    if number(total) and number(ebitda) and ebitda > 0:
        approx(report, f"{path}.metrics.debt_burden_pct",
               get(metrics, "debt_burden_pct"), 100 * total / ebitda, 0.11)
    elif number(ebitda) and ebitda <= 0:
        report.add("warning", f"{path}.metrics.debt_burden_pct",
                   "Nonpositive EBITDA: debt burden interpretation needs policy definition")

    market = get(inputs, "collateral_market_value")
    haircut = get(inputs, "collateral_haircut_pct")
    amount = get(inputs, "loan_amount")
    ltv = get(metrics, "ltv_pct")
    if market is None:
        if ltv is not None:
            report.add("error", f"{path}.metrics.ltv_pct", "LTV must be null without collateral")
    elif all(number(v) for v in (market, haircut, amount)):
        effective = market * (1 - haircut / 100)
        if effective <= 0 or not (0 <= haircut < 100):
            report.add("error", f"{path}.inputs.collateral_haircut_pct", "Invalid effective collateral value")
        else:
            approx(report, f"{path}.metrics.ltv_pct", ltv, amount / effective * 100, 0.11)
    else:
        report.add("error", f"{path}.inputs.collateral_market_value", "Invalid collateral inputs")

    stop = get(assessment, "stop_factor_checks")
    escalation = get(assessment, "escalation_checks")
    green = get(assessment, "green_zone_checks")
    for key, checks in (("stop_factor_checks", stop),
                        ("escalation_checks", escalation),
                        ("green_zone_checks", green)):
        if not isinstance(checks, list) or not all(isinstance(x, dict) for x in checks):
            report.add("error", f"{path}.{key}", "Expected array of objects")
            return
    # Verify flags against actual inputs where policy thresholds are unambiguous.
    rule_actuals = {
        "dscr_below_0_9": (get(metrics, "dscr"), lambda v: v < 0.9),
        "cash_flow_negative_over_3m": (
            get(inputs, "cash_flow_negative_months"), lambda v: v > 3
        ),
    }
    for i, check in enumerate(stop):
        code = check.get("code")
        if code in rule_actuals:
            actual, is_triggered = rule_actuals[code]
            if number(actual) and check.get("triggered") is not is_triggered(actual):
                report.add("error", f"{path}.stop_factor_checks[{i}].triggered",
                           f"Incorrect flag for {code}")

    for i, check in enumerate(green):
        code = check.get("code")
        expected = None
        if code == "dscr" and number(get(metrics, "dscr")):
            expected = get(metrics, "dscr") >= 1.1
        elif code == "ltv":
            ltv_value = get(metrics, "ltv_pct")
            expected = ltv_value <= 70 if number(ltv_value) else None
        elif code == "amount_limit":
            amount_value = get(inputs, "loan_amount")
            turnover = get(inputs, "annual_turnover")
            if number(amount_value) and number(turnover):
                expected = amount_value <= min(5_000_000, 0.2 * turnover)
        if code in {"dscr", "ltv", "amount_limit"} and check.get("passed") != expected:
            report.add("error", f"{path}.green_zone_checks[{i}].passed",
                       f"Incorrect {code} flag; expected {expected}")

    risk_score = get(assessment, "ai_scoring", "risk_score")
    confidence = get(assessment, "ai_scoring", "model_confidence_pct")
    for name, value in (("risk_score", risk_score), ("model_confidence_pct", confidence)):
        if require_number(report, f"{path}.ai_scoring.{name}", value):
            if not 0 <= value <= 100:
                report.add("error", f"{path}.ai_scoring.{name}", "Expected value between 0 and 100")

    stop_active = any(c.get("triggered") is True for c in stop)
    escalation_active = any(c.get("triggered") is True for c in escalation)
    all_green = all(c.get("passed") is not False for c in green)
    route = get(assessment, "route")
    if stop_active and route != "auto_decline":
        report.add("error", f"{path}.route", "Triggered stop factor requires auto_decline")
    elif not stop_active and route == "auto_decline":
        report.add("error", f"{path}.route", "auto_decline requires a triggered stop factor")
    if not stop_active and escalation_active and route != "analyst_escalation":
        report.add("error", f"{path}.route", "Escalation reason requires analyst_escalation")
    if route == "green_zone" and (stop_active or escalation_active or not all_green):
        report.add("error", f"{path}.route", "green_zone conflicts with checks")


def validate_dataset(profiles: list[dict], applications: list[dict],
                     assessments: list[dict] | None = None) -> QualityReport:
    """Check semantic consistency of generated reference records."""
    assessments = [] if assessments is None else assessments
    report = QualityReport(counts={"profiles": len(profiles),
                                   "applications": len(applications),
                                   "assessments": len(assessments)})
    for items, name, id_field in ((profiles, "profiles", "borrower_id"),
                                  (applications, "applications", "application_id"),
                                  (assessments, "assessments", "assessment_id")):
        seen: set[str] = set()
        for i, item in enumerate(items):
            id_value = get(item, id_field)
            if not isinstance(id_value, str) or not id_value.strip():
                report.add("error", f"{name}[{i}].{id_field}", "Missing ID")
            elif id_value in seen:
                report.add("error", f"{name}[{i}].{id_field}", "Duplicate ID")
            else:
                seen.add(id_value)

    borrowers = {p["borrower_id"] for p in profiles
                 if isinstance(p, dict) and isinstance(p.get("borrower_id"), str)}
    app_ids = {a["application_id"] for a in applications
               if isinstance(a, dict) and isinstance(a.get("application_id"), str)}
    for i, p in enumerate(profiles):
        if isinstance(p, dict):
            check_profile(p, report, f"profiles[{i}]")
        else:
            report.add("error", f"profiles[{i}]", "Expected JSON object")
    for i, a in enumerate(applications):
        if isinstance(a, dict):
            check_application(a, borrowers, report, f"applications[{i}]")
        else:
            report.add("error", f"applications[{i}]", "Expected JSON object")
    for i, a in enumerate(assessments):
        if isinstance(a, dict):
            check_assessment(a, app_ids, report, f"assessments[{i}]")
        else:
            report.add("error", f"assessments[{i}]", "Expected JSON object")
    return report


def read_json_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON array")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate synthetic MMB data quality")
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--applications", type=Path, required=True)
    parser.add_argument("--assessments", type=Path)
    parser.add_argument("--report", type=Path, default=Path("quality_report.json"))
    args = parser.parse_args()
    report = validate_dataset(
        read_json_records(args.profiles),
        read_json_records(args.applications),
        read_json_records(args.assessments) if args.assessments else [],
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Passed: {report.passed}; issues: {len(report.issues)}; report: {args.report}")
    for issue in report.issues[:12]:
        print(f"  [{issue.level}] {issue.path}: {issue.message}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
