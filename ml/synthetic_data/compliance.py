"""Synthetic bank-compliance enrichment for SME Borrower Profiles.

Illustrative test-data generator, NOT a sanctions screening service, AML decision,
FNS response, actual bank policy, or empirical prevalence estimate.

Contract quirk: ``fns_data.has_account_block_115fz`` represents a BANK signal.
We preserve the agreed JSON shape but populate it here, never in fns.py.

Only changes: compliance, fns_data.has_account_block_115fz, and (when a block is
created) bank_account.status. All other data, including BKI/financials, is kept.

Run after company.py -> bki.py -> fns.py.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from bki import financial_stress_proxy

SCENARIOS = ("baseline", "stress_2025", "demo")
SOURCE = "synthetic_internal_screening"


def _utc_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an ISO 8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp: {label}") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{label} must be UTC")
    return parsed


def _prefixes(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("restricted_okved_prefixes must be a sequence")
    result = tuple(values)
    if any(not isinstance(s, str) or not s or not all(ch.isdigit() or ch == "." for ch in s)
           for s in result):
        raise ValueError("Invalid restricted OKVED prefix")
    return result


def validate_compliance_profile(
    profile: dict[str, Any], *, restricted_okved_prefixes: Sequence[str] = ()
) -> None:
    """Check the local compliance/contract invariants, not external sanctions truth."""
    if not isinstance(profile, dict):
        raise ValueError("Profile must be an object")
    check = profile.get("compliance")
    fns = profile.get("fns_data")
    bank = profile.get("bank_account")
    company = profile.get("company")
    if not all(isinstance(obj, dict) for obj in (check, fns, bank, company)):
        raise ValueError("compliance, fns_data, bank_account, company must be objects")
    _utc_timestamp(check.get("checked_at"), "compliance.checked_at")
    _utc_timestamp(fns.get("retrieved_at"), "fns_data.retrieved_at")
    if check.get("source") != SOURCE:
        raise ValueError("Invalid compliance.source")
    for name in ("sanctions_hit", "is_prohibited_activity"):
        if type(check.get(name)) is not bool:
            raise ValueError(f"compliance.{name} must be boolean")
    if type(fns.get("has_account_block_115fz")) is not bool:
        raise ValueError("fns_data.has_account_block_115fz must be boolean")
    if fns["has_account_block_115fz"] and bank.get("status") != "blocked":
        raise ValueError("A flagged 115-FZ bank account restriction needs bank_account.status=blocked")
    if bank.get("status") not in {"active", "blocked", "closed"}:
        raise ValueError("Invalid bank_account.status")
    code = company.get("okved_main", {})
    if not isinstance(code, dict) or not isinstance(code.get("code"), str):
        raise ValueError("Missing company.okved_main.code")
    restricted = _prefixes(restricted_okved_prefixes)
    if restricted and check["is_prohibited_activity"] != code["code"].startswith(restricted):
        raise ValueError("is_prohibited_activity must agree with the specified synthetic OKVED policy")
    if _utc_timestamp(check["checked_at"], "compliance.checked_at") < _utc_timestamp(
        fns["retrieved_at"], "fns_data.retrieved_at"
    ):
        raise ValueError("Compliance screening predates source data retrieval")


def generate_compliance_data(
    profile: dict[str, Any], *, rng: np.random.Generator,
    scenario: str = "baseline", restricted_okved_prefixes: Sequence[str] = (),
) -> tuple[dict[str, Any], bool]:
    """Produce compliance fields and banking restriction flag for one profile.

    Sanctions hits are independent of financial stress; sanctions do not result
    from poor financial performance. Explicit prohibited OKVED policy is demo
    only; no industry in this generator is implicitly prohibited by law.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown compliance scenario: {scenario}")
    restricted = _prefixes(restricted_okved_prefixes)
    if restricted and scenario != "demo":
        raise ValueError("Synthetic restricted OKVED policy is allowed only with scenario=demo")
    try:
        fns = profile["fns_data"]
        old = profile["compliance"]
        company = profile["company"]
        bank = profile["bank_account"]
        code = company["okved_main"]["code"]
        checked_at = old["checked_at"]
        retrieved_at = fns["retrieved_at"]
        _utc_timestamp(checked_at, "compliance.checked_at")
        _utc_timestamp(retrieved_at, "fns_data.retrieved_at")
        if _utc_timestamp(checked_at, "compliance.checked_at") < _utc_timestamp(
            retrieved_at, "fns_data.retrieved_at"
        ):
            raise ValueError("compliance.checked_at predates FNS data")
        if bank["status"] not in {"active", "blocked", "closed"}:
            raise ValueError("Unexpected bank account status")
        if not isinstance(code, str):
            raise ValueError("OKVED code must be a string")
        if type(fns["has_tax_activity"]) is not bool:
            raise ValueError("has_tax_activity must be boolean")
        if type(fns["is_mass_address"]) is not bool or type(fns["is_mass_director"]) is not bool:
            raise ValueError("Invalid FNS boolean fields")
        stress = financial_stress_proxy(profile)
        weak = profile["bki_data"]["credit_history_quality"] == "weak"
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid input profile: {exc}") from exc

    # In production this would come from actual screening, not RNG.
    p_sanctions = {"baseline": 0.0005, "stress_2025": 0.0005, "demo": 0.035}[scenario]
    sanctions_hit = bool(rng.random() < p_sanctions)

    # Synthetic internal banking policy. NOT legal bans on these industries.
    prohibited = bool(restricted and code.startswith(restricted))

    # This flag means a FULL synthetic account restriction, not mere AML suspicion
    # or denial of a specific transaction. Financial vulnerability is only an
    # illustrative correlation, not evidence of suspicious activity.
    tax_inactive = not fns["has_tax_activity"]
    mass_registration = fns["is_mass_address"] or fns["is_mass_director"]
    weak_add = 0.004 if weak else 0.0
    p_bank_block = min(0.35,
        0.0015 + 0.012 * stress + weak_add
        + (0.010 if tax_inactive else 0.0)
        + (0.008 if mass_registration else 0.0)
        + {"baseline": 0.0, "stress_2025": 0.011, "demo": 0.075}[scenario],
    )
    # Preserve any pre-existing restrictions rather than silently clearing.
    account_block = bool(fns["has_account_block_115fz"] or rng.random() < p_bank_block)
    if account_block and bank["status"] == "closed":
        raise ValueError("Cannot add an active 115-FZ restriction to a closed account")

    return ({
        "checked_at": checked_at,
        "source": SOURCE,
        "sanctions_hit": sanctions_hit,
        "is_prohibited_activity": prohibited,
    }, account_block)


def fill_profiles(
    profiles: list[dict[str, Any]], *, seed: int = 45,
    scenario: str = "baseline", restricted_okved_prefixes: Sequence[str] = (),
) -> list[dict[str, Any]]:
    if not isinstance(profiles, list):
        raise TypeError("profiles must be a JSON array")
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    restricted = _prefixes(restricted_okved_prefixes)
    if restricted and scenario != "demo":
        raise ValueError("Synthetic restricted OKVED policy is permitted only in demo")
    rng = np.random.default_rng(seed)
    output = deepcopy(profiles)
    seen: set[str] = set()
    for idx, profile in enumerate(output):
        try:
            borrower_id = profile["borrower_id"]
            if not isinstance(borrower_id, str) or not borrower_id or borrower_id in seen:
                raise ValueError("Missing or duplicate borrower_id")
            seen.add(borrower_id)
            check, blocked = generate_compliance_data(
                profile, rng=rng, scenario=scenario,
                restricted_okved_prefixes=restricted,
            )
            profile["compliance"] = check
            profile["fns_data"]["has_account_block_115fz"] = blocked
            if blocked:
                profile["bank_account"]["status"] = "blocked"
            validate_compliance_profile(profile, restricted_okved_prefixes=restricted)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"profiles[{idx}]: {exc}") from exc
    return output


def summarize(
    profiles: list[dict[str, Any]], *, seed: int, scenario: str,
    restricted_okved_prefixes: Sequence[str] = (),
) -> dict[str, Any]:
    count = len(profiles)
    flags = Counter()
    for profile in profiles:
        check = profile["compliance"]
        fns = profile["fns_data"]
        flags["sanctions_hit"] += check["sanctions_hit"]
        flags["prohibited_activity"] += check["is_prohibited_activity"]
        flags["account_block_115fz"] += fns["has_account_block_115fz"]
        flags["any_compliance_stop"] += (
            check["sanctions_hit"] or check["is_prohibited_activity"] or
            fns["has_account_block_115fz"]
        )
    return {
        "count": count, "seed": seed, "scenario": scenario,
        "synthetic_restricted_okved_prefixes": list(restricted_okved_prefixes),
        "counts": dict(flags),
        "shares": {k: round(flags[k] / count, 4) if count else 0.0 for k in (
            "sanctions_hit", "prohibited_activity", "account_block_115fz", "any_compliance_stop"
        )},
        "limitations": [
            "All flags are synthetic; no real sanctions-screening list or bank policy is queried",
            "Sanctions probability is independent of financials; matches are not real accusations",
            "The optional OKVED restriction is a FICTIONAL demo bank policy, NOT a legal ban",
            "115-FZ flag is stored in fns_data solely for backward compatibility with team JSON",
            "115-FZ flag represents full restriction; actual law distinguishes refusals and restrictions",
            "Screening timestamps come from the original synthetic profile, not real checks",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Add synthetic bank compliance checks")
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--seed", type=int, default=45)
    parser.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    parser.add_argument("--restricted-okved-prefix", action="append", default=[],
                        help="FICTIONAL demo-only bank policy; repeat for several codes")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.out.resolve() == args.profiles.resolve():
        parser.error("--out must be different from --profiles")
    if args.out.exists() and not args.overwrite:
        parser.error("Output exists; pass --overwrite to replace it")
    if args.summary_out:
        if args.summary_out.resolve() in (args.out.resolve(), args.profiles.resolve()):
            parser.error("--summary-out must be different from inputs and --out")
        if args.summary_out.exists() and not args.overwrite:
            parser.error("Summary exists; pass --overwrite to replace it")
    try:
        input_profiles = json.loads(args.profiles.read_text(encoding="utf-8-sig"))
        output = fill_profiles(input_profiles, seed=args.seed, scenario=args.scenario,
                               restricted_okved_prefixes=args.restricted_okved_prefix)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    stats = summarize(output, seed=args.seed, scenario=args.scenario,
                      restricted_okved_prefixes=args.restricted_okved_prefix)
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Enriched {len(output)} profiles -> {args.out}")
    print("Compliance shares:", stats["shares"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
