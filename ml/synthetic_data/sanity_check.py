"""Exploratory diagnostics for generated SME Borrower Profiles.

Not a regulatory validator or a statistical goodness-of-fit test. Counts and
percentages describe YOUR synthetic sample; rates are not real bank estimates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
from typing import Any


def longest_negative_streak(flows: list[int | float]) -> int:
    current = best = 0
    for value in flows:
        current = current + 1 if value < 0 else 0
        best = max(best, current)
    return best


def audit(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("Expected nonempty JSON array of profiles")
    n = len(profiles)
    legal = Counter()
    bki = Counter()
    financial = []
    counts = Counter()
    borrower_ids, inn_values, ogrn_values = [], [], []
    for row in profiles:
        c, f = row["company"], row["financials"]
        tax, credit = row["fns_data"], row["bki_data"]
        comp = row["compliance"]
        account = row["bank_account"]
        borrower_ids.append(row["borrower_id"])
        inn_values.append(c["inn"])
        ogrn_values.append(c["ogrn"])
        legal[c["legal_form"]] += 1
        bki[credit["credit_history_quality"]] += 1
        turnover = f["annual_turnover"]
        financial.append(turnover)
        counts["zero_employees"] += c["employees_count"] == 0
        counts["zero_employees_ooo"] += c["legal_form"] == "ooo" and c["employees_count"] == 0
        counts["negative_ebitda"] += f["ebitda"] < 0
        counts["declining_revenue"] += f["revenue_change_pct"] < 0
        counts["four_negative_cashflow_months"] += longest_negative_streak(f["cash_flow_last_12m"]) >= 4
        counts["annual_debt_service_over_turnover"] += turnover > 0 and 12 * credit["monthly_debt_service"] > turnover
        counts["debt_over_turnover"] += turnover > 0 and credit["total_debt_amount"] > turnover
        counts["tax_debt"] += tax["tax_arrears_amount"] > 0
        counts["tax_inactive_with_turnover_gt_10m"] += not tax["has_tax_activity"] and turnover > 10_000_000
        counts["nonactive_registry_active_customer"] += tax["egrul_status"] != "active" and row["status"] == "active"
        counts["mass_address"] += tax["is_mass_address"]
        counts["mass_director"] += tax["is_mass_director"]
        counts["sanctions_hit"] += comp["sanctions_hit"]
        counts["prohibited_activity"] += comp["is_prohibited_activity"]
        counts["account_block_115fz"] += tax["has_account_block_115fz"]
        counts["block_account_status_mismatch"] += tax["has_account_block_115fz"] and account["status"] != "blocked"
    counts["duplicate_borrower_ids"] = n - len(set(borrower_ids))
    counts["duplicate_inn"] = n - len(set(inn_values))
    counts["duplicate_ogrn"] = n - len(set(ogrn_values))
    shares = {key: round(count / n, 4) for key, count in counts.items()}
    return {
        "n": n,
        "legal_form_counts": dict(legal),
        "bki_history_counts": dict(bki),
        "turnover_median_rub": median(financial),
        "counts": dict(counts),
        "shares": shares,
        "interpretation": [
            "Descriptive diagnostics, not FNS/BKI/AML prevalence estimates",
            "Registry non-active vs bank active is a review candidate, not necessarily contradiction",
            "A business may have annual debt service greater than turnover; flag for review",
            "No reference population or inferential realism assessment is provided",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize synthetic SME sample")
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.profiles.resolve() == args.out.resolve():
        parser.error("Output must differ from input")
    if args.out.exists() and not args.overwrite:
        parser.error("Report exists. Pass --overwrite")
    try:
        rows = json.loads(args.profiles.read_text(encoding="utf-8-sig"))
        result = audit(rows)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audited {result['n']} profiles -> {args.out}")
    print("Shares:", result["shares"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
