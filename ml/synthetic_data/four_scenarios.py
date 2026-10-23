"""Four reproducible demo borrower scenarios for the SME credit-conveyor MVP.

No random draws. We intentionally start from a versioned example Borrower Profile,
then set the fields needed for each case. The assessments come from the REAL
local rule-based assessment.py (not hand-authored expected outcomes).

This is a demo of routing up to Credit Assessment, NOT contract approval,
loan disbursement, or reliable real-world credit-risk prediction.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import blake2b
import json
from pathlib import Path
from typing import Any

from applications import PURPOSES, preliminary_limit, validate_application
from assessment import assess_applications
from validation import validate_dataset

BASE_PROFILE = Path(__file__).resolve().parent / "tests" / "fixtures" / "profiles.json"
CASES = ("ideal", "high_risk", "borderline", "new_business")
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def stable_id(prefix: str, tag: str, time: datetime) -> str:
    """Stable 26-character ULID for a fixed tag/time, not random output."""
    millis = int(time.timestamp() * 1000)
    entropy = int.from_bytes(blake2b(tag.encode("utf-8"), digest_size=10).digest(), "big")
    value = (millis << 80) | entropy
    letters = []
    for _ in range(26):
        letters.append(ALPHABET[value & 31])
        value >>= 5
    return prefix + "_" + "".join(reversed(letters))


def inn_ooo(index: int) -> str:
    digits = "77" + f"{1000000 + index:07d}"
    weights = (2, 4, 10, 3, 5, 9, 4, 6, 8)
    return digits + str(sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10)


def inn_person(index: int) -> str:
    digits = "77" + f"{30000000 + index:08d}"
    w1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    w2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    with_check = digits + str(sum(int(d) * w for d, w in zip(digits, w1)) % 11 % 10)
    return with_check + str(sum(int(d) * w for d, w in zip(with_check, w2)) % 11 % 10)


def registration_number(form: str, index: int, year: int) -> str:
    if form == "ooo":
        body = "1" + f"{year % 100:02d}" + "77" + f"{1000000 + index:07d}"
        return body + str(int(body) % 11 % 10)
    body = "3" + f"{year % 100:02d}" + "77" + f"{100000000 + index:09d}"
    return body + str(int(body) % 13 % 10)


def _stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _base_profile() -> dict[str, Any]:
    payload = json.loads(BASE_PROFILE.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("Expected one reference profile in tests/fixtures/profiles.json")
    return payload[0]


def make_case(case: str, index: int, template: dict[str, Any]) -> tuple[dict, dict]:
    if case not in CASES:
        raise ValueError(f"Unsupported scenario: {case}")
    now = datetime(2026, 10, 20, 11, 8, tzinfo=timezone.utc)
    p = deepcopy(template)
    app_created = now + timedelta(hours=1)
    p["borrower_id"] = stable_id("brw", case, now)
    p["status"] = "active"
    p["created_at"] = "2026-10-19T08:00:00Z"
    p["updated_at"] = _stamp(now)
    p["customer_since"] = "2026-10-19"
    p["documents"] = []  # No stale references to documents from the template.

    settings = {
        "ideal": dict(name="Меридиан", legal_form="ooo", registered="2020-03-12",
                      employees=12, turnover=30_000_000, ebitda=8_000_000,
                      growth=5.0, flows=[250_000] * 12, history="good",
                      debt=0, monthly=0, overdue=0, days=0, amount=2_000_000),
        "high_risk": dict(name="Шторм", legal_form="ooo", registered="2019-06-10",
                          employees=8, turnover=8_000_000, ebitda=-200_000,
                          growth=-25.0, flows=[-80_000] * 5 + [100_000] * 7,
                          history="weak", debt=1_600_000, monthly=60_000,
                          overdue=100_000, days=45, amount=1_000_000),
        "borderline": dict(name="Рубеж", legal_form="ooo", registered="2018-02-05",
                           employees=23, turnover=20_000_000, ebitda=9_000_000,
                           growth=4.0, flows=[250_000] * 12, history="good",
                           debt=0, monthly=0, overdue=0, days=0, amount=4_500_000),
        "new_business": dict(name="ИП Орлова", legal_form="ip", registered="2026-04-01",
                             employees=2, turnover=3_000_000, ebitda=800_000,
                             growth=0.0, flows=[0] * 6 + [50_000] * 6,
                             history="none", debt=0, monthly=0,
                             overdue=0, days=0, amount=300_000),
    }
    s = settings[case]
    form, registered = s["legal_form"], date.fromisoformat(s["registered"])
    head_name = ("Орлова Екатерина Павловна" if form == "ip"
                 else ("Петрова Анна Сергеевна" if case == "ideal"
                       else "Соколов Михаил Андреевич" if case == "high_risk"
                       else "Зайцев Павел Сергеевич"))
    company = p["company"]
    company.update({
        "legal_form": form,
        "full_name": (f"Общество с ограниченной ответственностью «{s['name']}»"
                      if form == "ooo" else f"Индивидуальный предприниматель {head_name}"),
        "short_name": (f"ООО «{s['name']}»" if form == "ooo" else f"ИП {head_name}"),
        "inn": inn_ooo(index) if form == "ooo" else inn_person(index),
        "kpp": ("770101001" if form == "ooo" else None),
        "ogrn": registration_number(form, index, registered.year),
        "registration_date": registered.isoformat(),
        "employees_count": s["employees"],
        "legal_address": "Тестовый адрес (вымышленный), Москва",
        "actual_address": "Тестовый адрес (вымышленный), Москва",
        "okved_main": {"code": "62.01", "name": "Разработка компьютерного программного обеспечения"},
        "tax_system": "usn_income_expense",
        "region_code": "77",
    })
    p["head"].update({"full_name": head_name,
                      "position": "Генеральный директор" if form == "ooo" else "Индивидуальный предприниматель",
                      "inn_individual": inn_person(index),
                      "in_position_since": registered.isoformat()})
    p["owners"] = [{"owner_id": stable_id("own", case, now),
                    "owner_type": "individual", "name": head_name,
                    "inn": inn_person(index), "ownership_share_pct": 100.0,
                    "is_beneficiary": True, "has_signing_authority": True}]
    p["contacts"] = {"phone": "+70000000000", "email": f"{case}@example.invalid",
                     "contact_person": {"full_name": head_name,
                                        "position": p["head"]["position"], "phone": "+70000000000"}}
    p["bank_account"].update({"account_number": "40702810" + f"{index:012d}",
                              "opened_at": "2026-04-10" if case == "new_business" else "2020-07-01",
                              "status": "active", "currency": "RUB"})
    p["financials"] = {
        "as_of_date": "2026-09-30", "annual_turnover": s["turnover"],
        "revenue_change_pct": s["growth"], "ebitda": s["ebitda"],
        "cash_flow_period_end": "2026-09", "cash_flow_last_12m": s["flows"],
        "source": "bank_statements",
    }
    p["bki_data"].update({
        "retrieved_at": "2026-10-20T10:08:05Z", "bureau": "Синтетическое БКИ",
        "credit_history_quality": s["history"],
        "active_loans_count": 1 if s["debt"] else 0,
        "total_debt_amount": s["debt"], "monthly_debt_service": s["monthly"],
        "overdue_amount": s["overdue"], "max_overdue_days_12m": s["days"],
    })
    p["fns_data"].update({
        "retrieved_at": "2026-10-20T10:07:12Z", "egrul_status": "active",
        "bankruptcy_status": "bankruptcy" if case == "high_risk" else "none",
        "has_account_block_115fz": False, "is_mass_address": False,
        "is_mass_director": False, "has_tax_activity": True,
        "tax_arrears_amount": 250_000 if case == "high_risk" else 0,
    })
    p["compliance"].update({"checked_at": "2026-10-20T10:07:40Z",
                            "source": "internal_screening", "sanctions_hit": False,
                            "is_prohibited_activity": False})

    created, credit, preapproved, submitted = (app_created,
        app_created + timedelta(minutes=2), app_created + timedelta(minutes=7),
        app_created + timedelta(minutes=15))
    purpose = "working_capital"
    app = {
        "application_id": stable_id("app", case, created),
        "application_number": f"ММБ-2026-TEST-{index:02d}",
        "borrower_id": p["borrower_id"],
        "status": "application_submitted", "status_changed_at": _stamp(submitted),
        "routing_status": "not_routed", "current_assessment_id": None,
        "loan_request": {"amount": s["amount"], "currency": "RUB",
                         "term_months": 24, "repayment_type": "annuity"},
        "purpose": {"category": purpose, "description": PURPOSES[purpose]},
        "collateral": {"type": "none", "description": None, "market_value": None,
                       "haircut_pct": None, "valuation_source": None},
        "pre_approval": {"max_amount": preliminary_limit(s["turnover"]),
                         "indicative_rate_pct": 22.0, "calculated_at": _stamp(preapproved)},
        "consents": {"data_processing_at": _stamp(created),
                     "credit_history_check_at": _stamp(credit),
                     "submit_confirmed_at": _stamp(submitted)},
        "document_requirements": [],
        "assignment": {"analyst_user_id": None, "underwriter_user_id": None},
        "closure": None,
        "created_at": _stamp(created), "updated_at": _stamp(submitted),
    }
    validate_application(app, p)
    return p, app


def build_four_scenarios() -> dict[str, Any]:
    template = _base_profile()
    pairs = [make_case(case, i, template) for i, case in enumerate(CASES, 1)]
    profiles, submitted_apps = [a for a, b in pairs], [b for a, b in pairs]
    assessments, assessed_apps, summary = assess_applications(profiles, submitted_apps)
    report = validate_dataset(profiles, assessed_apps, assessments)
    if not report.passed:
        raise ValueError(f"Scenario validation failed: {report.to_dict()['issues']}")
    expected = {
        "ideal": {"route": "green_zone", "stop_factor": None, "counter_trigger": None},
        "high_risk": {"route": "auto_decline", "stop_factor": "bankruptcy", "counter_trigger": None},
        "borderline": {"route": "analyst_escalation", "stop_factor": None,
                       "counter_trigger": "amount_limit_exceeded", "recommended_amount": 4_000_000},
        "new_business": {"route": "analyst_escalation", "stop_factor": None,
                         "escalation_trigger": "business_age_lt_12m", "counter_trigger": None},
    }
    for case, assessment in zip(CASES, assessments):
        wanted = expected[case]
        if assessment["route"] != wanted["route"]:
            raise AssertionError(f"{case}: expected {wanted['route']}, got {assessment['route']}")
        active_stop = {c["code"] for c in assessment["stop_factor_checks"] if c["triggered"]}
        if wanted["stop_factor"] and wanted["stop_factor"] not in active_stop:
            raise AssertionError(f"{case}: expected stop factor {wanted['stop_factor']}")
        if wanted["stop_factor"] is None and active_stop:
            raise AssertionError(f"{case}: unexpected stop factors {active_stop}")
        counter = {c["code"]: c for c in assessment["counter_offer_triggers"]}
        if wanted.get("counter_trigger") and wanted["counter_trigger"] not in counter:
            raise AssertionError(f"{case}: expected counter-offer trigger")
        if wanted.get("counter_trigger") is None and counter:
            raise AssertionError(f"{case}: unexpected counter-offer triggers")
        if "recommended_amount" in wanted:
            amount = counter[wanted["counter_trigger"]]["recommended_terms"]["amount"]
            if amount != wanted["recommended_amount"]:
                raise AssertionError(f"{case}: expected revised amount {wanted['recommended_amount']}, got {amount}")
        if wanted.get("escalation_trigger"):
            active_escalations = {c["code"] for c in assessment["escalation_checks"] if c["triggered"]}
            if wanted["escalation_trigger"] not in active_escalations:
                raise AssertionError(f"{case}: missing young-business escalation")
    return {"profiles.json": profiles, "applications.json": submitted_apps,
            "assessments.json": assessments, "applications_assessed.json": assessed_apps,
            "expected_outcomes.json": expected,
            "summary.json": {"case_order": list(CASES), "scenario_count": len(CASES),
                             "route_counts": summary["route_counts"],
                             "validation": report.to_dict(),
                             "policy_version": summary["policy_version"],
                             "model_version": summary["model_version"]}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build four deterministic E2E borrower scenarios")
    parser.add_argument("--out-dir", type=Path,
                        default=Path(__file__).resolve().parent / "tests" / "fixtures" / "end_to_end")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    files = build_four_scenarios()
    target = args.out_dir
    if target.exists() and not target.is_dir():
        parser.error("--out-dir must be a directory")
    existing = [str(target / filename) for filename in files if (target / filename).exists()]
    if existing and not args.overwrite:
        parser.error(f"Output already exists: {existing}. Use --overwrite to regenerate")
    target.mkdir(parents=True, exist_ok=True)
    for filename, payload in files.items():
        (target / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    print(f"Generated {len(CASES)} fixed scenarios in {target}")
    print("Routes:", files["summary.json"]["route_counts"])
    print("Validator:", files["summary.json"]["validation"]["passed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
