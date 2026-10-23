"""Synthetic (rule-based) Credit Assessments for an educational SME-lending MVP.

No trained ML model, real PD/default outcomes, or real bank decision is produced.
Policy thresholds are from the team's provisional 2026.10 contract; haircuts,
score, confidence and fallback routing are demo-only assumptions.

Generate immutable assessment snapshots AND updated copies of applications.
Input arrays remain unchanged. Final contractual approval belongs to an
underwriter; routing to green_zone does NOT issue a loan or final approval.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import blake2b
import json
from math import isfinite
from pathlib import Path
from typing import Any

from bki import financial_stress_proxy
from validation import longest_negative_streak, validate_dataset

POLICY_VERSION = "2026.10_demo"
MODEL_VERSION = "synthetic_rules_v0.1_not_ml"
# These policy haircuts are OUR assumptions, not sourced bank policy.
HAIRCUTS = {"real_estate": 30.0, "equipment": 40.0, "vehicle": 50.0}
ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _utc(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError("Timestamp must be UTC ISO 8601")
    return dt


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _assessment_id(application_id: str, at: datetime) -> str:
    """Deterministic ULID-like ID with actual millisecond timestamp."""
    ms = int(at.timestamp() * 1000)
    if not (0 <= ms < (1 << 48)):
        raise ValueError("Timestamp out of range")
    random80 = int.from_bytes(blake2b(application_id.encode(), digest_size=10).digest(), "big")
    value = (ms << 80) | random80
    digits = []
    for _ in range(26):
        digits.append(ULID_ALPHABET[value & 31])
        value >>= 5
    return "asm_" + "".join(reversed(digits))


def monthly_annuity(amount: int, term_months: int, annual_rate_pct: float) -> float:
    """Standard fixed payment (monthly rate = nominal annual rate / 12)."""
    if amount <= 0 or term_months <= 0 or not (0 <= annual_rate_pct < 100):
        raise ValueError("Invalid loan terms")
    r = annual_rate_pct / 1200
    return amount / term_months if r == 0 else amount * r / (1 - (1 + r) ** -term_months)


def first_year_debt_service(amount: int, months: int, rate_pct: float,
                            repayment_type: str) -> int:
    """Payments due over min(12, term_months) months, rounded to rubles."""
    if repayment_type not in {"annuity", "differentiated"}:
        raise ValueError("Unknown repayment type")
    if amount <= 0 or months <= 0 or not (0 <= rate_pct < 100):
        raise ValueError("Invalid loan terms")
    payments = min(months, 12)
    if repayment_type == "annuity":
        return round(monthly_annuity(amount, months, rate_pct) * payments)
    monthly_principal = amount / months
    rate = rate_pct / 1200
    return round(sum(monthly_principal + max(0.0, amount - i * monthly_principal) * rate
                     for i in range(payments)))


def age_in_months(registered: date, at: date) -> int:
    if at < registered:
        raise ValueError("Application predates registration")
    return (at.year - registered.year) * 12 + at.month - registered.month - (at.day < registered.day)


def _check(code: str, triggered: bool, actual: Any, source: str, group: str) -> dict:
    return {"code": code, "group": group, "triggered": bool(triggered),
            "actual": actual, "source": source}


def _green(code: str, actual: Any, op: str, threshold: Any,
           passed: bool | None) -> dict:
    return {"code": code, "actual": actual, "operator": op,
            "threshold": threshold, "passed": passed}


def _counter(code: str, action: str, amount: int | None = None,
             months: int | None = None, rate_delta: float | None = None) -> dict:
    return {"code": code, "triggered": True, "recommended_action": action,
            "recommended_terms": {"amount": amount, "term_months": months,
                                  "rate_delta_pp": rate_delta}}


def assess_one(profile: dict, app: dict, *, mock_confidence_pct: float = 90.0
               ) -> tuple[dict, dict]:
    """Return (assessment, updated_application), preserving the originals."""
    if not 0 <= mock_confidence_pct <= 100 or not isfinite(mock_confidence_pct):
        raise ValueError("mock_confidence_pct must be between 0 and 100")
    if profile["borrower_id"] != app["borrower_id"]:
        raise ValueError("Application borrower_id mismatch")
    if app["status"] != "application_submitted" or app["current_assessment_id"] is not None:
        raise ValueError("Only unassessed stage-4 applications are accepted")

    f, b, tax, comp = (profile[k] for k in ("financials", "bki_data", "fns_data", "compliance"))
    request, collateral = app["loan_request"], app["collateral"]
    amount, term = request["amount"], request["term_months"]
    rate = float(app["pre_approval"]["indicative_rate_pct"])
    ebitda, turnover = int(f["ebitda"]), int(f["annual_turnover"])
    existing = 12 * int(b["monthly_debt_service"])
    new = first_year_debt_service(amount, term, rate, request["repayment_type"])
    total = existing + new
    if total <= 0:
        raise ValueError("New loan must have positive debt service")
    dscr = round(ebitda / total, 4)
    # Nonpositive EBITDA is not an interpretable positive debt burden: null.
    debt_burden = round(100 * total / ebitda, 2) if ebitda > 0 else None

    pledged = collateral["type"] in HAIRCUTS
    market = int(collateral["market_value"]) if pledged else None
    haircut = HAIRCUTS[collateral["type"]] if pledged else None
    ltv = round(100 * amount / (market * (1 - haircut / 100)), 2) if pledged else None

    created = _utc(app["updated_at"]) + timedelta(minutes=1)
    stamp = _stamp(created)
    age = age_in_months(date.fromisoformat(profile["company"]["registration_date"]), created.date())
    streak = longest_negative_streak(f["cash_flow_last_12m"])
    growth = float(f["revenue_change_pct"])
    quality = b["credit_history_quality"]
    credit_stress = financial_stress_proxy(profile)
    tax_arrears_ratio = float(tax["tax_arrears_amount"]) / max(1, turnover)
    # Higher scores imply LOWER synthetic risk; no default probability implied.
    score = round(max(0.0, min(100.0,
        95 - 45 * credit_stress - (20 if quality == "weak" else 0)
        - (8 if quality == "none" else 0) - 20 * min(1, tax_arrears_ratio)
    )))
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "E"

    stop = [
        _check("bankruptcy", tax["bankruptcy_status"] == "bankruptcy", tax["bankruptcy_status"], "fns_data.bankruptcy_status", "legal"),
        _check("observation_procedure", tax["bankruptcy_status"] == "observation", tax["bankruptcy_status"], "fns_data.bankruptcy_status", "legal"),
        _check("account_blocked_115fz", tax["has_account_block_115fz"], tax["has_account_block_115fz"], "fns_data.has_account_block_115fz", "legal"),
        _check("sanctions", comp["sanctions_hit"], comp["sanctions_hit"], "compliance.sanctions_hit", "legal"),
        _check("prohibited_activity", comp["is_prohibited_activity"], comp["is_prohibited_activity"], "compliance.is_prohibited_activity", "legal"),
        _check("cash_flow_negative_over_3m", streak > 3, streak, "inputs.cash_flow_negative_months", "financial"),
        _check("dscr_below_0_9", dscr < 0.9, dscr, "metrics.dscr", "financial"),
        _check("mass_address", tax["is_mass_address"], tax["is_mass_address"], "fns_data.is_mass_address", "fictitiousness"),
        _check("mass_director", tax["is_mass_director"], tax["is_mass_director"], "fns_data.is_mass_director", "fictitiousness"),
        _check("no_tax_activity", not tax["has_tax_activity"], tax["has_tax_activity"], "fns_data.has_tax_activity", "fictitiousness"),
    ]
    # Conservative review when official registry and bank customer snapshots disagree.
    conflicts = int(tax["egrul_status"] != "active" and profile["status"] == "active")
    escalation = [
        {"code": "business_age_lt_12m", "triggered": age < 12, "actual": age, "threshold": 12},
        {"code": "model_confidence_lt_80", "triggered": mock_confidence_pct < 80,
         "actual": mock_confidence_pct, "threshold": 80},
        {"code": "conflicting_sources", "triggered": conflicts > 0,
         "actual": conflicts, "threshold": 0},
    ]
    amount_limit = min(5_000_000, 0.20 * turnover)
    green = [
        _green("amount_limit", amount, "<=", amount_limit, amount <= amount_limit),
        _green("dscr", dscr, ">=", 1.1, dscr >= 1.1),
        _green("ltv", ltv, "<=", 70.0, ltv <= 70 if ltv is not None else None),
        _green("revenue_change", growth, ">", -20.0, growth > -20),
        _green("credit_history", quality, "!=", "weak", quality != "weak"),
    ]

    counter = []
    if amount > amount_limit:
        counter.append(_counter("amount_limit_exceeded", "reduce_amount_to_limit",
                                amount=int(amount_limit) if amount_limit >= 100_000 else None))
    if 0.9 <= dscr < 1.1:
        extended = None
        for candidate in (12, 18, 24, 36, 48, 60, 72):
            if candidate > term:
                candidate_service = first_year_debt_service(amount, candidate, rate, request["repayment_type"])
                if ebitda / (existing + candidate_service) >= 1.1:
                    extended = candidate
                    break
        counter.append(_counter("dscr_below_threshold", "extend_term", months=extended))
    if ltv is not None and ltv > 70:
        max_amt = int(0.70 * market * (1 - haircut / 100))
        counter.append(_counter("ltv_exceeded", "reduce_amount_or_add_collateral",
                                amount=max_amt if max_amt >= 100_000 else None))
    if growth <= -20 or quality == "weak":
        counter.append(_counter("above_average_risk", "raise_rate", rate_delta=2.0))

    stop_codes = [c["code"] for c in stop if c["triggered"]]
    escalation_codes = [c["code"] for c in escalation if c["triggered"]]
    all_green = all(c["passed"] is not False for c in green)
    acceptable_grade = grade in {"A", "B", "C"}
    if stop_codes:
        route = "auto_decline"
    elif escalation_codes or not all_green or not acceptable_grade:
        # Provisional choice: no separate counter-offer route in the contract.
        # Unresolved counter-offers are routed to analyst, NOT silently approved.
        route = "analyst_escalation"
    else:
        route = "green_zone"
    if route == "auto_decline":
        # Do not propose conditional offers once a hard stop factor fired.
        counter = []

    assessment = {
        "assessment_id": _assessment_id(app["application_id"], created),
        "application_id": app["application_id"],
        "sequence": 1,
        "status": "completed", "trigger": "initial",
        "policy_version": POLICY_VERSION, "model_version": MODEL_VERSION,
        "calculated_at": stamp,
        "inputs": {
            "loan_amount": amount, "term_months": term, "rate_pct": rate,
            "annual_turnover": turnover, "ebitda": ebitda,
            "existing_debt_service_12m": existing,
            "new_debt_service_12m": new, "total_future_debt_service": total,
            "collateral_market_value": market, "collateral_haircut_pct": haircut,
            "business_age_months": age, "revenue_change_pct": growth,
            "cash_flow_negative_months": streak, "credit_history_quality": quality,
        },
        "metrics": {"dscr": dscr, "ltv_pct": ltv, "debt_burden_pct": debt_burden},
        "ai_scoring": {"risk_grade": grade, "risk_score": score,
                       "model_confidence_pct": mock_confidence_pct},
        "stop_factor_checks": stop, "escalation_checks": escalation,
        "green_zone_checks": green,
        "route": route, "counter_offer_triggers": counter,
        "auto_decline": ({
            "reason_codes": stop_codes,
            "client_explanation": "Автоматическая проверка выявила стоп-факторы.",
            "declined_at": stamp,
        } if route == "auto_decline" else None),
        "ai_credit_memo": {
            "summary": ("Синтетический расчёт: " +
                        ("сработали стоп-факторы" if stop_codes else
                         "необходима ручная проверка или изменение условий" if route == "analyst_escalation" else
                         "выполнены демонстрационные условия зелёной зоны")),
            "key_risks": stop_codes + escalation_codes + [c["code"] for c in counter],
            "recommendation": ("decline" if stop_codes else "counter_offer" if counter else "approve"),
            "generated_at": stamp,
        },
        "analyst_conclusion": None,
        "created_at": stamp,
    }
    updated_app = deepcopy(app)
    updated_app["current_assessment_id"] = assessment["assessment_id"]
    updated_app["routing_status"] = "auto_declined" if route == "auto_decline" else route
    updated_app["status"] = ("auto_declined" if route == "auto_decline" else
                             "underwriter_review" if route == "green_zone" else "analyst_escalation")
    updated_app["status_changed_at"] = stamp
    updated_app["updated_at"] = stamp
    if route == "auto_decline":
        updated_app["closure"] = {"closed_at": stamp, "reason": "auto_declined"}
    return assessment, updated_app


def assess_applications(profiles: list[dict], applications: list[dict], *,
                        mock_confidence_pct: float = 90.0) -> tuple[list[dict], list[dict], dict]:
    """Create one assessment for each application; return assessments, apps, summary."""
    by_id = {p["borrower_id"]: p for p in profiles}
    if len(by_id) != len(profiles):
        raise ValueError("Duplicate borrower_id")
    seen = set()
    results, updated, routes = [], [], Counter()
    for app in applications:
        appid = app["application_id"]
        if appid in seen:
            raise ValueError(f"Duplicate application_id: {appid}")
        seen.add(appid)
        if app["borrower_id"] not in by_id:
            raise ValueError(f"Unknown borrower_id: {app['borrower_id']}")
        assessment, app_out = assess_one(by_id[app["borrower_id"]], app,
                                         mock_confidence_pct=mock_confidence_pct)
        results.append(assessment)
        updated.append(app_out)
        routes[assessment["route"]] += 1
    return results, updated, {
        "count": len(results), "route_counts": dict(routes),
        "policy_version": POLICY_VERSION, "model_version": MODEL_VERSION,
        "mock_confidence_pct": mock_confidence_pct,
        "limitations": [
            "NOT a trained ML risk model: risk_score/risk_grade are deterministic demo heuristics",
            "model_confidence_pct is explicitly a MOCK CONSTANT and is NOT calibrated",
            "Nonpositive EBITDA uses null debt_burden_pct (contract clarification required)",
            "Haircuts 30/40/50% are hypothetical; bank policy must be confirmed",
            "For failed green checks, provisional route=analyst_escalation pending team agreement",
            "Green Zone is routing only, never final loan approval",
            "No credit offers, contracts, AI verification documents or default labels generated",
        ],
    }


def _json(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic rule-based Credit Assessments")
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--applications", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="assessments output")
    parser.add_argument("--applications-out", type=Path, required=True, help="updated applications output")
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--mock-confidence-pct", type=float, default=90.0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    inputs = [args.profiles, args.applications]
    outputs = [p for p in (args.out, args.applications_out, args.summary_out) if p]
    if len(set(map(lambda x: x.resolve(), inputs + outputs))) != len(inputs + outputs):
        parser.error("Input and output file paths must all be distinct")
    if any(p.exists() for p in outputs) and not args.overwrite:
        parser.error("Output file exists; use --overwrite to replace")
    profiles, applications = _json(args.profiles), _json(args.applications)
    assessments, updated, summary = assess_applications(
        profiles, applications, mock_confidence_pct=args.mock_confidence_pct)
    report = validate_dataset(profiles, updated, assessments)
    if not report.passed:
        parser.error("Assessment failed validation: " + str(report.to_dict()["issues"][:3]))
    for target, data in ((args.out, assessments), (args.applications_out, updated),
                         (args.summary_out, summary)):
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Assessed {len(assessments)} applications; routes: {summary['route_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
