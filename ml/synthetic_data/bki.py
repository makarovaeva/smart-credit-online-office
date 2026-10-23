"""Synthetic credit bureau (BKI) enrichment for existing Borrower Profiles.

Usage from repository root (with uv project in backend/):
    uv run --project backend --group ml python ml/synthetic_data/bki.py \
        --profiles ml/synthetic_data/data/profiles_companies.json \
        --out ml/synthetic_data/data/profiles_bki.json \
        --seed 43 --scenario baseline

Inputs are unchanged; only the `bki_data` block is replaced in each profile.
Output cannot overwrite input. Existing output requires --overwrite.
Requires: numpy.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date
import json
from math import isfinite, log1p
from pathlib import Path
from typing import Any

import numpy as np

SCENARIOS = ("baseline", "stress_2025")


def _clip(x: float, low: float, high: float) -> float:
    return min(high, max(low, x))


def financial_stress_proxy(profile: dict[str, Any]) -> float:
    """Observable stress proxy ∈ [0,1] from generated financials.

    Original `financials.py` does not export its hidden efficiency/stress draws,
    so BKI uses financial signals. It does not claim to recover the latent state.
    """
    f = profile["financials"]
    revenue = float(f["annual_turnover"])
    ebitda = float(f["ebitda"])
    growth = float(f["revenue_change_pct"])
    flows = f["cash_flow_last_12m"]

    if not all(isfinite(v) for v in (revenue, ebitda, growth)) or revenue <= 0:
        raise ValueError("financials must have positive finite turnover and finite EBITDA/growth")
    if not isinstance(flows, list) or len(flows) != 12 or any(
        type(v) not in (int, float) or not isfinite(v) for v in flows
    ):
        raise ValueError("cash_flow_last_12m must contain 12 finite numbers")

    margin = ebitda / revenue
    negative_fraction = sum(value < 0 for value in flows) / 12
    # 0% at EBITDA margin >= 10%, approaches 100% if margin <= -10%.
    margin_distress = _clip((0.10 - margin) / 0.20, 0.0, 1.0)
    # 0% if YoY >= 0; reaches 100% when YoY <= -30%.
    growth_distress = _clip(-growth / 30.0, 0.0, 1.0)
    return _clip(
        0.40 * margin_distress + 0.25 * growth_distress +
        0.35 * negative_fraction,
        0.0, 1.0,
    )


def _annuity_payment(principal: int, annual_rate: float, months: int) -> int:
    """Illustrative equal monthly payment, rounded to rubles."""
    r = annual_rate / 12
    if r == 0:
        return round(principal / months)
    return round(principal * r / (1.0 - (1.0 + r) ** (-months)))


def _check_positive_number(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be a positive finite number")
    return float(value)


def generate_bki_data(
    profile: dict[str, Any],
    *,
    rng: np.random.Generator,
    scenario: str = "baseline",
) -> dict[str, Any]:
    """Generate one BKI contract block conditional on company and financials.

    Sampling parameters are illustrative, not measured credit-bureau frequencies.
    `none` means no prior loans; `good`/`weak` can have zero *active* loans.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown BKI scenario: {scenario}")
    try:
        f = profile["financials"]
        c = profile["company"]
        revenue = _check_positive_number(f["annual_turnover"], "annual_turnover")
        employees = c["employees_count"]
        if type(employees) is not int or employees < 0:
            raise ValueError("employees_count must be a nonnegative int")
        registered = date.fromisoformat(c["registration_date"])
        reporting_date = date.fromisoformat(f["as_of_date"])
        if registered > reporting_date:
            raise ValueError("registration_date exceeds financials.as_of_date")
        retrieved_at = profile["fns_data"]["retrieved_at"]
        # BKI is captured at the same synthetic retrieval time as FNS.
        if not isinstance(retrieved_at, str) or not retrieved_at.endswith("Z"):
            raise ValueError("fns_data.retrieved_at must be a UTC timestamp ending in Z")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Incomplete Borrower Profile: {exc}") from exc

    age_years = max(0.0, (reporting_date - registered).days / 365.25)
    stress = financial_stress_proxy(profile)
    # P(ever borrowed) grows with size and age, not an observed population rate.
    p_history = _clip(
        0.46 + 0.065 * log1p(employees) +
        0.10 * log1p(revenue / 5_000_000) +
        0.035 * min(age_years, 10),
        0.10, 0.94,
    )
    has_history = bool(rng.random() < p_history)
    if not has_history:
        return {
            "retrieved_at": retrieved_at,
            "bureau": "synthetic_bki",
            "credit_history_quality": "none",
            "active_loans_count": 0,
            "total_debt_amount": 0,
            "monthly_debt_service": 0,
            "overdue_amount": 0,
            "max_overdue_days_12m": 0,
        }

    stress_addition = 0.08 if scenario == "stress_2025" else 0.0
    p_weak = _clip(0.065 + 0.37 * stress + stress_addition, 0.01, 0.80)
    weak = bool(rng.random() < p_weak)
    quality = "weak" if weak else "good"

    p_active = _clip(
        0.45 + 0.055 * log1p(employees) +
        0.085 * log1p(revenue / 5_000_000) - 0.05 * stress,
        0.15, 0.85,
    )
    active = bool(rng.random() < p_active)
    if active:
        count = int(rng.choice([1, 2, 3, 4], p=[0.70, 0.23, 0.06, 0.01]))
        # Roughly 0.26 × annual turnover before scaling; strongly right-skewed.
        debt_to_turnover = _clip(
            float(rng.lognormal(mean=-1.35, sigma=0.66)) *
            (1.0 + 0.30 * (count - 1)) * (1.0 + 0.25 * stress),
            0.015, 1.50,
        )
        debt = max(10_000, round(revenue * debt_to_turnover))
        proportions = rng.dirichlet(np.full(count, 1.5))
        portions = [round(debt * float(frac)) for frac in proportions[:-1]]
        portions.append(debt - sum(portions))
        monthly_service = 0
        for principal in portions:
            months = int(rng.choice([12, 24, 36, 48, 60], p=[0.08, 0.20, 0.35, 0.26, 0.11]))
            annual_rate = float(rng.uniform(0.14, 0.32))  # illustrative only
            monthly_service += _annuity_payment(principal, annual_rate, months)
        monthly_service = max(1, monthly_service)
    else:
        count = 0
        debt = 0
        monthly_service = 0

    # Weak history has a late-payment event during the past 12 months.
    # Current overdue debt may already have been repaid or closed.
    max_days = int(rng.choice([5, 15, 30, 60, 90, 120], p=[0.12, 0.22, 0.25, 0.22, 0.14, 0.05])) if weak else 0
    if weak and active and rng.random() < 0.50:
        overdue_ratio = float(rng.uniform(0.005, 0.20))
        overdue = max(1, min(debt, round(debt * overdue_ratio)))
    else:
        overdue = 0

    record = {
        "retrieved_at": retrieved_at,
        "bureau": "synthetic_bki",
        "credit_history_quality": quality,
        "active_loans_count": count,
        "total_debt_amount": debt,
        "monthly_debt_service": monthly_service,
        "overdue_amount": overdue,
        "max_overdue_days_12m": max_days,
    }
    validate_bki_data(record)
    return record


def validate_bki_data(data: dict[str, Any]) -> None:
    """Local BKI invariants not yet covered by the project-wide validator."""
    if data.get("credit_history_quality") not in {"none", "good", "weak"}:
        raise ValueError("Invalid credit_history_quality")
    for field in ("active_loans_count", "total_debt_amount", "monthly_debt_service", "overdue_amount", "max_overdue_days_12m"):
        v = data.get(field)
        if type(v) is not int or v < 0:
            raise ValueError(f"{field} must be a nonnegative integer")
    loans = data["active_loans_count"]
    debt = data["total_debt_amount"]
    service = data["monthly_debt_service"]
    overdue = data["overdue_amount"]
    days = data["max_overdue_days_12m"]
    if (loans == 0) != (debt == 0) or (loans == 0) != (service == 0):
        raise ValueError("Loan count, debt and debt service must agree on zero/nonzero")
    if overdue > debt:
        raise ValueError("Overdue amount cannot exceed total debt")
    if data["credit_history_quality"] == "none" and (loans or days or overdue):
        raise ValueError("No credit history cannot contain active loans or past-due events")
    if data["credit_history_quality"] == "good" and (overdue or days):
        raise ValueError("Good synthetic history should not contain overdue events")
    if data["credit_history_quality"] == "weak" and days == 0:
        raise ValueError("Weak synthetic history needs a past-due event")


def fill_profiles(
    profiles: list[dict[str, Any]],
    *,
    seed: int = 43,
    scenario: str = "baseline",
) -> list[dict[str, Any]]:
    """Return copies with only bki_data replaced (inputs never mutated)."""
    if not isinstance(profiles, list):
        raise TypeError("profiles must be a JSON array")
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown BKI scenario: {scenario}")
    rng = np.random.default_rng(seed)
    output = deepcopy(profiles)
    seen: set[str] = set()
    for i, profile in enumerate(output):
        try:
            borrower_id = profile["borrower_id"]
            if not isinstance(borrower_id, str) or not borrower_id:
                raise ValueError("Invalid borrower_id")
            if borrower_id in seen:
                raise ValueError("Duplicate borrower_id")
            seen.add(borrower_id)
            profile["bki_data"] = generate_bki_data(profile, rng=rng, scenario=scenario)
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"profiles[{i}]: {exc}") from exc
    return output


def summarize(profiles: list[dict[str, Any]], *, seed: int, scenario: str) -> dict[str, Any]:
    total = len(profiles)
    counts = Counter(profile["bki_data"]["credit_history_quality"] for profile in profiles)
    active = sum(p["bki_data"]["active_loans_count"] > 0 for p in profiles)
    overdue = sum(p["bki_data"]["overdue_amount"] > 0 for p in profiles)
    return {
        "seed": seed, "scenario": scenario, "count": total,
        "quality_counts": dict(counts),
        "quality_shares": {key: round(counts.get(key, 0) / total, 4) if total else 0.0
                           for key in ("none", "good", "weak")},
        "active_loans_share": round(active / total, 4) if total else 0.0,
        "current_overdue_share": round(overdue / total, 4) if total else 0.0,
        "limitations": [
            "All probabilities, rates and term assumptions are illustrative, not Russian BKI estimates",
            "BKI distress uses a proxy from financial data, not the original hidden financial generator factors",
            "Credit history quality is a heuristic classification, not a bureau-provided grade",
            "No default labels, PD calibration, live bureau requests or credit decisions",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich generated Borrower Profiles with synthetic BKI")
    parser.add_argument("--profiles", type=Path, required=True, help="Existing profiles JSON array")
    parser.add_argument("--out", type=Path, required=True, help="New profiles JSON (cannot be input)")
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    parser.add_argument("--summary-out", type=Path, help="Optional statistics JSON")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing OUT file")
    args = parser.parse_args()

    if args.profiles.resolve() == args.out.resolve():
        parser.error("--out must differ from --profiles (input is never overwritten)")
    if args.out.exists() and not args.overwrite:
        parser.error("Output already exists. Pass --overwrite to replace it")
    if args.summary_out is not None:
        if args.summary_out.resolve() in {args.profiles.resolve(), args.out.resolve()}:
            parser.error("--summary-out must be different from --profiles and --out")
        if args.summary_out.exists() and not args.overwrite:
            parser.error("Summary already exists. Pass --overwrite to replace it")

    try:
        profiles = json.loads(args.profiles.read_text(encoding="utf-8-sig"))
        result = fill_profiles(profiles, seed=args.seed, scenario=args.scenario)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        parser.error(str(exc))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = summarize(result, seed=args.seed, scenario=args.scenario)
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Enriched {len(result)} profiles -> {args.out}")
    print("BKI shares:", stats["quality_shares"])
    print("Active debt share:", stats["active_loans_share"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
