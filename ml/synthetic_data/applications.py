"""Generate synthetic Loan Application records from existing Borrower Profiles.

Input: JSON array of Borrower Profiles AFTER company/bki/fns/compliance stages.
Output: JSON array of Loan Applications. This module never modifies profiles,
calculates risk scores, approves loans, or simulates repayment outcomes.

All probabilities and the preliminary rate are illustrative, NOT observed
bank-applicant frequencies or real bank policy. One application per borrower
in this MVP; no active-application or historical versions are simulated.

Example (run from repository root):
    uv run --project backend --group ml python ml/synthetic_data/applications.py \
        --profiles ml/synthetic_data/data/profiles_compliance.json \
        --out ml/synthetic_data/data/applications_generated.json \
        --summary-out ml/synthetic_data/data/applications_summary.json \
        --seed 46 --scenario baseline
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import numpy as np

SCENARIOS = ("baseline", "demo")
PURPOSES = {
    "working_capital": "Пополнение оборотных средств",
    "equipment": "Приобретение оборудования",
    "real_estate": "Приобретение коммерческой недвижимости",
    "other": "Развитие бизнеса",
}
TERM_MONTHS = (6, 12, 18, 24, 36, 48, 60)
TERM_PROBABILITIES = (0.05, 0.13, 0.12, 0.29, 0.25, 0.11, 0.05)
_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _parse_utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be a UTC timestamp ending with Z")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {field}") from exc
    if result.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return result


def _as_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ulid(dt: datetime, rng: np.random.Generator) -> str:
    """26-character ULID with a deterministic timestamp and random suffix."""
    timestamp_ms = int(dt.timestamp() * 1000)
    if not 0 <= timestamp_ms < (1 << 48):
        raise ValueError("Application timestamp outside ULID range")
    value = (timestamp_ms << 80) | int.from_bytes(rng.bytes(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ULID_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def _purpose(okved: str, rng: np.random.Generator) -> str:
    """Illustrative conditional mix, not a measured distribution."""
    if okved.startswith("62"):
        weights = (0.67, 0.18, 0.03, 0.12)
    elif okved.startswith(("41", "01")):
        weights = (0.39, 0.27, 0.24, 0.10)
    elif okved.startswith(("46", "47", "56")):
        weights = (0.70, 0.20, 0.03, 0.07)
    else:
        weights = (0.50, 0.32, 0.08, 0.10)
    return str(rng.choice(tuple(PURPOSES), p=weights))


def preliminary_limit(turnover: int | float) -> int:
    """MVP simplification: green-zone amount cap, NOT a credit approval."""
    if isinstance(turnover, bool) or not isinstance(turnover, (int, float)):
        raise ValueError("annual_turnover must be a number")
    if not np.isfinite(turnover) or turnover < 0:
        raise ValueError("annual_turnover must be finite and nonnegative")
    return int(min(5_000_000, 0.20 * turnover))


def _request_amount(limit: int, turnover: float, rng: np.random.Generator,
                    scenario: str) -> int:
    """Oversample loan requests near/above the preliminary cap for testing.

    The cap drives the distribution in this simulation. This does not imply
    real applicants know their bank's eligibility thresholds.
    """
    if scenario == "demo":
        band = str(rng.choice(("within", "near", "above"), p=(0.28, 0.35, 0.37)))
    else:
        band = str(rng.choice(("within", "near", "above"), p=(0.62, 0.18, 0.20)))
    if band == "within":
        factor = float(rng.uniform(0.20, 0.88))
    elif band == "near":
        factor = float(rng.uniform(0.97, 1.03))
    else:
        factor = float(rng.uniform(1.15, 2.35))
    # There is no positive amount <=0 when the turnover-based limit is zero.
    fallback = max(100_000, min(1_000_000, int(turnover * 0.12)))
    proposed = factor * limit if limit > 0 else fallback * factor
    return min(20_000_000, max(100_000, int(round(proposed / 10_000)) * 10_000))


def _collateral(amount: int, purpose: str, legal_form: str,
                rng: np.random.Generator) -> dict[str, Any]:
    """Borrower-proposed collateral; haircut is assigned at a later stage."""
    secured_probability = 0.19 + (0.16 if amount > 1_500_000 else 0.0)
    if purpose == "real_estate":
        secured_probability += 0.52
    if purpose == "equipment":
        secured_probability += 0.12
    if legal_form == "ip":
        secured_probability -= 0.04
    secured_probability = float(np.clip(secured_probability, 0.03, 0.90))

    if rng.random() >= secured_probability:
        collateral_type = str(rng.choice(("none", "guarantee"), p=(0.87, 0.13)))
    elif purpose == "real_estate":
        collateral_type = str(rng.choice(("real_estate", "equipment", "vehicle"),
                                         p=(0.85, 0.10, 0.05)))
    elif purpose == "equipment":
        collateral_type = str(rng.choice(("equipment", "vehicle", "real_estate"),
                                         p=(0.65, 0.20, 0.15)))
    else:
        collateral_type = str(rng.choice(("real_estate", "equipment", "vehicle"),
                                         p=(0.37, 0.43, 0.20)))

    if collateral_type in ("none", "guarantee"):
        # A personal guarantee has no separately measurable pledged asset value.
        return {
            "type": collateral_type,
            "description": None if collateral_type == "none" else "Поручительство собственника",
            "market_value": None,
            "haircut_pct": None,
            "valuation_source": None,
        }

    # Market value is declared by the client, not verified by an appraiser.
    # LTV is computed later using policy-specific haircuts in assessment.py.
    coverage = float(rng.lognormal(mean=0.35, sigma=0.55))
    market_value = int(max(100_000, round(amount * coverage / 1_000) * 1_000))
    descriptions = {
        "real_estate": "Коммерческая недвижимость (заявленная стоимость)",
        "equipment": "Производственное оборудование (заявленная стоимость)",
        "vehicle": "Транспортное средство (заявленная стоимость)",
    }
    return {
        "type": collateral_type,
        "description": descriptions[collateral_type],
        "market_value": market_value,
        "haircut_pct": None,
        "valuation_source": "client",
    }


def validate_application(application: dict[str, Any], profile: dict[str, Any]) -> None:
    """Local stage-4 contract checks; not a complete backend Pydantic schema."""
    if application["borrower_id"] != profile["borrower_id"]:
        raise ValueError("borrower_id does not match profile")
    if not application["application_id"].startswith("app_"):
        raise ValueError("application_id has the wrong prefix")
    if application["status"] != "application_submitted":
        raise ValueError("Expected application_submitted for stage-4 snapshot")
    if application["routing_status"] != "not_routed" or application["current_assessment_id"] is not None:
        raise ValueError("Stage-4 application cannot have a routing or assessment result")
    request = application["loan_request"]
    if type(request["amount"]) is not int or request["amount"] <= 0:
        raise ValueError("Loan amount must be a positive integer")
    if type(request["term_months"]) is not int or request["term_months"] <= 0:
        raise ValueError("Loan term must be a positive integer")
    if request["currency"] != "RUB" or request["repayment_type"] not in {"annuity", "differentiated"}:
        raise ValueError("Invalid loan currency or repayment type")
    collateral = application["collateral"]
    if collateral["type"] in ("none", "guarantee"):
        if collateral["market_value"] is not None or collateral["haircut_pct"] is not None:
            raise ValueError("No market-valued pledged collateral")
    elif collateral["type"] in ("real_estate", "equipment", "vehicle"):
        if type(collateral["market_value"]) is not int or collateral["market_value"] <= 0:
            raise ValueError("Pledged asset requires positive market_value")
        if collateral["haircut_pct"] is not None or collateral["valuation_source"] != "client":
            raise ValueError("Haircut is not known at stage 4; valuation comes from client")
    else:
        raise ValueError("Unknown collateral type")
    if application["document_requirements"] != [] or application["closure"] is not None:
        raise ValueError("Document requirements and closure must be empty at submission")
    if application["assignment"] != {"analyst_user_id": None, "underwriter_user_id": None}:
        raise ValueError("Employees are assigned later")
    consents = application["consents"]
    processed = _parse_utc_timestamp(consents["data_processing_at"], "data_processing_at")
    credit = _parse_utc_timestamp(consents["credit_history_check_at"], "credit_history_check_at")
    submitted = _parse_utc_timestamp(consents["submit_confirmed_at"], "submit_confirmed_at")
    preapproved = _parse_utc_timestamp(application["pre_approval"]["calculated_at"], "calculated_at")
    created = _parse_utc_timestamp(application["created_at"], "created_at")
    updated = _parse_utc_timestamp(application["updated_at"], "updated_at")
    status_changed = _parse_utc_timestamp(application["status_changed_at"], "status_changed_at")
    profile_updated = _parse_utc_timestamp(profile["updated_at"], "profile.updated_at")
    if not (profile_updated <= created <= processed <= credit <= preapproved <= submitted == updated == status_changed):
        raise ValueError("Invalid chronology of application and consents")
    if date.fromisoformat(profile["company"]["registration_date"]) > created.date():
        raise ValueError("Business registration is after application creation")
    if application["pre_approval"]["max_amount"] != preliminary_limit(profile["financials"]["annual_turnover"]):
        raise ValueError("Unexpected preliminary demo limit")


def generate_applications(profiles: list[dict[str, Any]], *, seed: int = 46,
                          scenario: str = "baseline", application_rate: float = 1.0,
                          indicative_rate_pct: float = 22.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate one submitted application per sampled borrower.

    Probability 1.0 is useful for integration coverage, not the real-world
    probability of an SME applying for a loan.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    if not isinstance(profiles, list):
        raise TypeError("profiles must be a JSON array")
    if isinstance(application_rate, bool) or not 0 <= application_rate <= 1:
        raise ValueError("application_rate must be between 0 and 1")
    if not np.isfinite(indicative_rate_pct) or not 0 < indicative_rate_pct < 100:
        raise ValueError("indicative_rate_pct must be in (0, 100)")
    rng = np.random.default_rng(seed)
    results: list[dict[str, Any]] = []
    seen_borrowers: set[str] = set()
    category_counts: Counter[str] = Counter()
    purpose_counts: Counter[str] = Counter()
    security_counts: Counter[str] = Counter()
    above_limit = 0
    for index, profile in enumerate(profiles, start=1):
        if not isinstance(profile, dict):
            raise ValueError(f"profiles[{index - 1}] is not a JSON object")
        try:
            borrower_id = profile["borrower_id"]
            financials = profile["financials"]
            turnover = financials["annual_turnover"]
            company = profile["company"]
            okved = company["okved_main"]["code"]
            legal_form = company["legal_form"]
            profile_updated = _parse_utc_timestamp(profile["updated_at"], "profile.updated_at")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid borrower profile at index {index - 1}: {exc}") from exc
        if not isinstance(borrower_id, str) or not borrower_id:
            raise ValueError("Missing borrower_id")
        if borrower_id in seen_borrowers:
            raise ValueError(f"Duplicate borrower_id: {borrower_id}")
        seen_borrowers.add(borrower_id)
        if not isinstance(okved, str) or legal_form not in {"ooo", "ip"}:
            raise ValueError("Invalid company OKVED or legal_form")
        limit = preliminary_limit(turnover)
        if rng.random() >= application_rate:
            continue

        # Create after the profile snapshot, preventing temporal leakage.
        created = profile_updated + timedelta(hours=1)
        processed = created
        credit = created + timedelta(minutes=2)
        preapproved = created + timedelta(minutes=7)
        submitted = created + timedelta(minutes=15)
        purpose = _purpose(okved, rng)
        amount = _request_amount(limit, turnover, rng, scenario)
        term = int(rng.choice(TERM_MONTHS, p=TERM_PROBABILITIES))
        repayment = str(rng.choice(("annuity", "differentiated"), p=(0.86, 0.14)))
        collateral = _collateral(amount, purpose, legal_form, rng)
        application = {
            "application_id": f"app_{_ulid(created, rng)}",
            "application_number": f"ММБ-{created.year}-{index:06d}",
            "borrower_id": borrower_id,
            "status": "application_submitted",
            "status_changed_at": _as_utc(submitted),
            "routing_status": "not_routed",
            "current_assessment_id": None,
            "loan_request": {
                "amount": amount,
                "currency": "RUB",
                "term_months": term,
                "repayment_type": repayment,
            },
            "purpose": {"category": purpose, "description": PURPOSES[purpose]},
            "collateral": collateral,
            "pre_approval": {
                "max_amount": limit,
                "indicative_rate_pct": float(indicative_rate_pct),
                "calculated_at": _as_utc(preapproved),
            },
            "consents": {
                "data_processing_at": _as_utc(processed),
                "credit_history_check_at": _as_utc(credit),
                "submit_confirmed_at": _as_utc(submitted),
            },
            "document_requirements": [],
            "assignment": {"analyst_user_id": None, "underwriter_user_id": None},
            "closure": None,
            "created_at": _as_utc(created),
            "updated_at": _as_utc(submitted),
        }
        validate_application(application, profile)
        results.append(application)
        category_counts["above_limit" if amount > limit else "within_limit"] += 1
        purpose_counts[purpose] += 1
        security_counts[collateral["type"]] += 1
        if amount > limit:
            above_limit += 1

    metadata = {
        "seed": seed,
        "scenario": scenario,
        "application_rate": application_rate,
        "indicative_rate_pct": indicative_rate_pct,
        "input_borrowers": len(profiles),
        "applications": len(results),
        "by_limit": dict(sorted(category_counts.items())),
        "by_purpose": dict(sorted(purpose_counts.items())),
        "by_collateral_type": dict(sorted(security_counts.items())),
        "above_preliminary_limit_share": round(above_limit / len(results), 4) if results else None,
        "notes": [
            "Stage-4 snapshots only; no risk scores, routes, decisions or offers generated",
            "Illustrative request distributions; NOT empirical applicant frequencies",
            "Pre-approval cap is simplified as min(5m RUB, 20% annual turnover)",
            "Collateral haircut is null until assessment/policy application",
            "One application per selected borrower in this MVP",
        ],
    }
    return results, metadata


def _read_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} should contain a JSON array")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic stage-4 Loan Applications")
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--seed", type=int, default=46)
    parser.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    parser.add_argument("--application-rate", type=float, default=1.0)
    parser.add_argument("--indicative-rate-pct", type=float, default=22.0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.profiles.resolve() == args.out.resolve():
        parser.error("Input and output paths must differ")
    if args.summary_out and args.summary_out.resolve() in {args.out.resolve(), args.profiles.resolve()}:
        parser.error("Summary output must have a separate path")
    for output in (args.out, args.summary_out):
        if output and output.exists() and not args.overwrite:
            parser.error(f"Output {output} exists; use --overwrite to replace")
    profiles = _read_array(args.profiles)
    applications, metadata = generate_applications(
        profiles, seed=args.seed, scenario=args.scenario,
        application_rate=args.application_rate,
        indicative_rate_pct=args.indicative_rate_pct,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(applications, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(applications)} applications from {len(profiles)} profiles -> {args.out}")
    print(f"Above preliminary limit: {metadata['above_preliminary_limit_share']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
