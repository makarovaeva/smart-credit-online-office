"""Synthetic FNS/registration-data enrichment of existing Borrower Profiles.


Pipeline: company.py -> bki.py -> fns.py -> validation.py
Only the ``fns_data`` block is replaced; financials, BKI and compliance
remain untouched. The existing contract historically includes the bank's
115-FZ flag in ``fns_data``. We deliberately preserve it unchanged because
it is not an ordinary FNS registry attribute.

Run (from repository root):
    uv run --project backend --group ml python ml/synthetic_data/fns.py \
      --profiles ml/synthetic_data/data/profiles_bki.json \
      --out ml/synthetic_data/data/profiles_fns.json \
      --summary-out ml/synthetic_data/data/fns_summary.json \
      --seed 44 --scenario baseline
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import json
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np

from bki import financial_stress_proxy

SCENARIOS = ("baseline", "stress_2025", "demo")
FIELDS = (
    "retrieved_at", "egrul_status", "bankruptcy_status",
    "has_account_block_115fz", "is_mass_address", "is_mass_director",
    "has_tax_activity", "tax_arrears_amount",
)


def _clip(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


def _valid_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("retrieved_at must be an ISO-8601 UTC timestamp ending with Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid retrieved_at") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("retrieved_at must be UTC")
    return parsed


def validate_fns_data(data: dict[str, Any], *, legal_form: str | None = None) -> None:
    """Enforce local schema and hard invariants of the synthetic FNS block."""
    if not isinstance(data, dict):
        raise ValueError("fns_data must be an object")
    missing = set(FIELDS) - set(data)
    if missing:
        raise ValueError(f"missing fns_data fields: {sorted(missing)}")
    _valid_utc(data["retrieved_at"])
    if data["egrul_status"] not in {"active", "liquidating", "liquidated"}:
        raise ValueError("invalid egrul_status")
    if data["bankruptcy_status"] not in {"none", "observation", "bankruptcy"}:
        raise ValueError("invalid bankruptcy_status")
    for field in (
        "has_account_block_115fz", "is_mass_address", "is_mass_director", "has_tax_activity"
    ):
        if type(data[field]) is not bool:
            raise ValueError(f"{field} must be boolean")
    debt = data["tax_arrears_amount"]
    if type(debt) is not int or debt < 0:
        raise ValueError("tax_arrears_amount must be a nonnegative integer")
    if legal_form == "ip":
        # A sole proprietor has no corporate registered office or director.
        if data["is_mass_address"] or data["is_mass_director"]:
            raise ValueError("mass-address/director markers not applicable to IP")
        if data["bankruptcy_status"] == "observation":
            raise ValueError("observation of a corporate debtor not applicable to IP")
        if data["egrul_status"] == "liquidating":
            raise ValueError("corporate liquidation marker not applicable to IP")
    if data["egrul_status"] == "liquidated" and data["bankruptcy_status"] == "observation":
        raise ValueError("completed liquidation cannot be in observation stage")


def generate_fns_data(
    profile: dict[str, Any], *, rng: np.random.Generator, scenario: str = "baseline"
) -> dict[str, Any]:
    """Draw FNS-like status and tax-risk fields conditional on company/financials.

    ``demo`` intentionally oversamples adverse states for QA, not estimation.
    ``stress_2025`` is a hypothetical stress scenario, not a 2025 reconstruction.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    try:
        company = profile["company"]
        prior = profile["fns_data"]
        legal_form = company["legal_form"]
        if legal_form not in {"ooo", "ip"}:
            raise ValueError("company.legal_form must be 'ooo' or 'ip'")
        registered = date.fromisoformat(company["registration_date"])
        fetched = _valid_utc(prior["retrieved_at"])
        if registered > fetched.date():
            raise ValueError("registration_date later than FNS retrieval")
        turnover = profile["financials"]["annual_turnover"]
        if type(turnover) not in (float, int) or not isfinite(turnover) or turnover <= 0:
            raise ValueError("financials.annual_turnover must be positive and finite")
        stress = financial_stress_proxy(profile)
        # Credit stress provides another imperfect but relevant signal.
        credit_weak = profile.get("bki_data", {}).get("credit_history_quality") == "weak"
        age_months = (fetched.year - registered.year) * 12 + fetched.month - registered.month
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid profile for FNS generation: {exc}") from exc

    # Hypothetical odds, NEVER fitted to FNS administrative data.
    extra = {"baseline": 0.0, "stress_2025": 0.055, "demo": 0.19}[scenario]
    p_debt = _clip(0.09 + 0.27 * stress + 0.04 * credit_weak + extra, 0.01, 0.88)
    has_tax_debt = bool(rng.random() < p_debt)
    # Right-skewed tax-arrears size as fraction of annual turnover.
    debt_ratio = _clip(float(rng.lognormal(mean=-4.35 + 0.65 * stress, sigma=0.90)),
                       0.0002, 0.18)
    tax_debt = max(1_000, int(round(float(turnover) * debt_ratio))) if has_tax_debt else 0

    p_inactive = _clip(
        0.008 + 0.036 * stress + (0.010 if age_months < 36 else 0.0) +
        {"baseline": 0.0, "stress_2025": 0.025, "demo": 0.09}[scenario],
        0.0, 0.38,
    )
    no_tax_activity = bool(rng.random() < p_inactive)

    # Bankruptcy/observation: rare in baseline, deliberately enriched in demo.
    p_insolvency = _clip(
        0.0004 + 0.009 * stress**2 + 0.002 * credit_weak +
        {"baseline": 0.0, "stress_2025": 0.006, "demo": 0.060}[scenario],
        0.0, 0.35,
    )
    if rng.random() < p_insolvency:
        bankruptcy = str(rng.choice(["observation", "bankruptcy"], p=[0.46, 0.54])) \
            if legal_form == "ooo" else "bankruptcy"
    else:
        bankruptcy = "none"

    # Corporate liquidation may accompany insolvency or be independent.
    if legal_form == "ooo":
        p_liquidating = _clip(
            0.003 + 0.015 * stress + (0.045 if bankruptcy != "none" else 0.0) +
            {"baseline": 0.0, "stress_2025": 0.008, "demo": 0.050}[scenario],
            0.0, 0.35,
        )
        status = "liquidating" if rng.random() < p_liquidating else "active"
    else:
        status = "active"

    if legal_form == "ooo":
        p_mass_address = _clip(
            0.010 + 0.018 * stress +
            {"baseline": 0.0, "stress_2025": 0.008, "demo": 0.075}[scenario],
            0.0, 0.33,
        )
        p_mass_director = _clip(
            0.005 + 0.012 * stress +
            {"baseline": 0.0, "stress_2025": 0.005, "demo": 0.060}[scenario],
            0.0, 0.30,
        )
        mass_address = bool(rng.random() < p_mass_address)
        mass_director = bool(rng.random() < p_mass_director)
    else:
        mass_address = False
        mass_director = False

    # Contract anomaly: 115-FZ banking indicator lives under fns_data.
    # Preserve existing value for later compliance enrichment; don't invent
    # an FNS source or silently clear a bank restriction.
    record = {
        "retrieved_at": prior["retrieved_at"],
        "egrul_status": status,
        "bankruptcy_status": bankruptcy,
        "has_account_block_115fz": prior["has_account_block_115fz"],
        "is_mass_address": mass_address,
        "is_mass_director": mass_director,
        "has_tax_activity": not no_tax_activity,
        "tax_arrears_amount": tax_debt,
    }
    validate_fns_data(record, legal_form=legal_form)
    return record


def fill_profiles(
    profiles: list[dict[str, Any]], *, seed: int = 44, scenario: str = "baseline"
) -> list[dict[str, Any]]:
    """Return deep-copied profiles with ONLY fns_data replaced."""
    if not isinstance(profiles, list):
        raise TypeError("profiles must be a JSON array")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    rng = np.random.default_rng(seed)
    result = deepcopy(profiles)
    seen: set[str] = set()
    for i, profile in enumerate(result):
        try:
            borrower_id = profile["borrower_id"]
            if not isinstance(borrower_id, str) or not borrower_id:
                raise ValueError("invalid borrower_id")
            if borrower_id in seen:
                raise ValueError("duplicate borrower_id")
            seen.add(borrower_id)
            profile["fns_data"] = generate_fns_data(profile, rng=rng, scenario=scenario)
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"profiles[{i}]: {exc}") from exc
    return result


def summarize(profiles: list[dict[str, Any]], *, seed: int, scenario: str) -> dict[str, Any]:
    count = len(profiles)
    status = Counter(p["fns_data"]["egrul_status"] for p in profiles)
    bankruptcy = Counter(p["fns_data"]["bankruptcy_status"] for p in profiles)
    def share(predicate) -> float:
        return round(sum(bool(predicate(p["fns_data"])) for p in profiles) / count, 4) if count else 0.0
    return {
        "count": count, "seed": seed, "scenario": scenario,
        "egrul_status_counts": dict(status),
        "bankruptcy_counts": dict(bankruptcy),
        "tax_arrears_share": share(lambda f: f["tax_arrears_amount"] > 0),
        "no_tax_activity_share": share(lambda f: not f["has_tax_activity"]),
        "mass_address_share": share(lambda f: f["is_mass_address"]),
        "mass_director_share": share(lambda f: f["is_mass_director"]),
        "any_fns_adverse_share": share(lambda f: (
            f["tax_arrears_amount"] > 0 or not f["has_tax_activity"]
            or f["egrul_status"] != "active" or f["bankruptcy_status"] != "none"
            or f["is_mass_address"] or f["is_mass_director"]
        )),
        "limitations": [
            "All probabilities and monetary ratios are hypothetical, not estimated FNS rates",
            "The cohort is conditional on 24+ month companies from company.py and is not representative",
            "bankruptcy_status is a cross-source aggregate, not necessarily a direct FNS response",
            "For IP the contract's egrul_status field semantically refers to EGRIP",
            "has_account_block_115fz is preserved for later bank/compliance simulation",
            "Sanctions, prohibited activities, credit decisions and real default labels are not generated",
            "demo deliberately oversamples adverse states for functional tests",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Add synthetic tax and company-registry signals")
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--seed", type=int, default=44)
    parser.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing output files")
    args = parser.parse_args()
    if args.out.resolve() == args.profiles.resolve():
        parser.error("--out must differ from --profiles")
    if args.out.exists() and not args.overwrite:
        parser.error("output exists; use --overwrite to replace it")
    if args.summary_out:
        if args.summary_out.resolve() in {args.out.resolve(), args.profiles.resolve()}:
            parser.error("--summary-out must differ from --out and --profiles")
        if args.summary_out.exists() and not args.overwrite:
            parser.error("summary exists; use --overwrite to replace it")
    try:
        profiles = json.loads(args.profiles.read_text(encoding="utf-8-sig"))
        result = fill_profiles(profiles, seed=args.seed, scenario=args.scenario)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = summarize(result, seed=args.seed, scenario=args.scenario)
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Enriched {len(result)} profiles -> {args.out}")
    print("FNS statistics:", {k: v for k, v in summary.items() if k.endswith("_share")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
