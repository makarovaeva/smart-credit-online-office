"""Generate plausible *synthetic* BorrowerProfile.financials for an MVP.

Usage:
    python financials.py --profiles tests/fixtures/profiles.json --out data/profiles_generated.json --seed 42
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from calendar import monthrange
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import numpy as np

# Illustrative assumptions. Calibrate these from public data later.
REVENUE_PER_WORKER_RUB = 3_000_000
INDUSTRY_MULTIPLIERS = {
    "01": 0.75,  # Agriculture
    "10": 0.95,  # Food manufacturing
    "41": 1.15,  # Construction
    "46": 1.35,  # Wholesale
    "47": 0.90,  # Retail
    "56": 0.65,  # Catering
    "62": 1.05,  # Software/IT
}


@dataclass(frozen=True)
class FinancialScenario:

    stressed_share: float
    growth_intercept: float
    growth_stress: float
    growth_sigma: float
    margin_intercept: float
    margin_stress: float
    margin_efficiency: float
    margin_t_scale: float
    cash_intercept: float
    cash_stress: float
    cash_noise_base: float
    cash_noise_stress: float
    cash_persistent_sigma: float


SCENARIOS: dict[str, FinancialScenario] = {
    # Explicit, editable hypotheses; see CALIBRATION.md for limitations.
    "baseline": FinancialScenario(
        stressed_share=0.15, growth_intercept=0.055,
        growth_stress=0.12, growth_sigma=0.12,
        margin_intercept=0.15, margin_stress=0.22,
        margin_efficiency=0.04, margin_t_scale=0.045,
        cash_intercept=0.05, cash_stress=0.04,
        cash_noise_base=0.035, cash_noise_stress=0.02,
        cash_persistent_sigma=0.035,
    ),
    "stress_2025": FinancialScenario(
        stressed_share=0.30, growth_intercept=0.005,
        growth_stress=0.17, growth_sigma=0.14,
        margin_intercept=0.155, margin_stress=0.23,
        margin_efficiency=0.05, margin_t_scale=0.065,
        cash_intercept=0.055, cash_stress=0.065,
        cash_noise_base=0.045, cash_noise_stress=0.030,
        cash_persistent_sigma=0.035,
    ),
}
# Historical benchmark of our original v0.1 model, not a third calibrated scenario.
SCENARIO_NAMES = (*SCENARIOS.keys(), "legacy_v01")


def last_closed_month(as_of_date: date) -> tuple[int, int]:
    """Return (year, month) of the latest *fully completed* calendar month."""
    if as_of_date.day == monthrange(as_of_date.year, as_of_date.month)[1]:
        return as_of_date.year, as_of_date.month
    if as_of_date.month == 1:
        return as_of_date.year - 1, 12
    return as_of_date.year, as_of_date.month - 1


def generate_financials(
    *,
    employees_count: int,
    okved_code: str,
    registration_date: date,
    as_of_date: date,
    rng: np.random.Generator,
    source: str = "documents",
    scenario: str = "baseline",
) -> dict:
    """Create one Financials block using correlated, stochastic quantities.

    v0.1 supports businesses with at least 24 completed operating months;
    newer businesses require an explicit contract for incomplete history.
    """
    if type(employees_count) is not int or employees_count < 0:
        raise ValueError("employees_count must be a nonnegative integer")
    if not isinstance(okved_code, str) or not okved_code:
        raise ValueError("okved_code must be a nonempty string")
    if not isinstance(registration_date, date) or not isinstance(as_of_date, date):
        raise TypeError("registration_date and as_of_date must be date objects")
    if source not in {"documents", "bank_statements", "fns"}:
        raise ValueError("Invalid financials.source")
    if scenario not in SCENARIO_NAMES:
        raise ValueError(f"Unknown financial scenario: {scenario}")
    period_year, period_month = last_closed_month(as_of_date)
    # A registration mid-month does not give a complete operating month.
    first_full_year, first_full_month = registration_date.year, registration_date.month
    if registration_date.day != 1:
        if first_full_month == 12:
            first_full_year, first_full_month = first_full_year + 1, 1
        else:
            first_full_month += 1
    complete_months = (
        (period_year - first_full_year) * 12
        + period_month - first_full_month + 1
    )
    if complete_months < 24:
        raise ValueError(
            "v0.1 requires >=24 completed operating months to simulate a full "
            "trailing year and YoY comparison; define young-business null policy first"
        )
    period_end = date(period_year, period_month, monthrange(period_year, period_month)[1])
    if registration_date > period_end:
        raise ValueError("Registration date is later than reporting period")

    # The two hidden factors are shared by turnover, growth, margins and
    # cash flow, creating *conditional* rather than independent variables.
    efficiency = float(rng.normal(0.0, 1.0))
    cfg = SCENARIOS.get(scenario)
    stressed_share = 0.15 if cfg is None else cfg.stressed_share
    # Preserve the exact historical sampling order in legacy_v01.
    if cfg is None:
        stress = float(rng.beta(2.0, 5.0) if rng.random() < 0.85
                       else rng.uniform(0.6, 1.0))
    else:
        stress = float(rng.beta(2.0, 5.0) if rng.random() >= stressed_share
                       else rng.uniform(0.6, 1.0))
    industry_multiplier = INDUSTRY_MULTIPLIERS.get(okved_code[:2], 1.0)
    base_turnover = (max(employees_count, 1) * REVENUE_PER_WORKER_RUB
                     * industry_multiplier)
    turnover = max(1, round(base_turnover * np.exp(
        0.22 * efficiency - 0.40 * stress + rng.normal(0.0, 0.45)
    )))

    if scenario == "legacy_v01":
        # Historical benchmark, copied from original financials.py.
        growth_fraction = float(np.clip(
            0.035 + 0.055 * efficiency - 0.21 * stress
            + rng.normal(0.0, 0.09), -0.75, 0.65
        ))
        margin = float(np.clip(
            0.17 + 0.035 * efficiency - 0.25 * stress
            + rng.normal(0.0, 0.04), -0.28, 0.42
        ))
    else:
        assert cfg is not None
        growth_fraction = float(np.clip(
            cfg.growth_intercept + 0.055 * efficiency
            - cfg.growth_stress * stress + rng.normal(0.0, cfg.growth_sigma),
            -0.75, 0.65,
        ))
        # Student-t (df=4) has heavier tails than a normal shock.
        # Clip avoids implausible infinities; bounds are model assumptions.
        margin = float(np.clip(
            cfg.margin_intercept + cfg.margin_efficiency * efficiency
            - cfg.margin_stress * stress + cfg.margin_t_scale * rng.standard_t(df=4),
            -0.60, 0.65,
        ))
    ebitda = round(turnover * margin)

    monthly_turnover = turnover / 12
    seasonal_phase = float(rng.uniform(0, 2 * np.pi))
    seasonal_amplitude = float(rng.uniform(0.0, 0.025))
    persistent_shock = 0.0 if cfg is None else float(
        rng.normal(0.0, cfg.cash_persistent_sigma)
    )
    cash_flows: list[int] = []
    for month in range(12):
        seasonal = seasonal_amplitude * np.sin(2 * np.pi * month / 12 + seasonal_phase)
        if cfg is None:
            noise = float(rng.normal(0.0, 0.025 + 0.055 * stress))
            cf_ratio = 0.45 * margin + 0.025 - 0.10 * stress + seasonal + noise
        else:
            noise = float(rng.normal(0.0, cfg.cash_noise_base
                                     + cfg.cash_noise_stress * stress))
            cf_ratio = (0.50 * margin + cfg.cash_intercept - cfg.cash_stress * stress
                        + persistent_shock + seasonal + noise)
        cash_flows.append(round(monthly_turnover * cf_ratio))

    return {
        "as_of_date": period_end.isoformat(),
        "annual_turnover": int(turnover),
        "revenue_change_pct": round(100 * growth_fraction, 2),
        "ebitda": int(ebitda),
        "cash_flow_period_end": f"{period_year:04d}-{period_month:02d}",
        "cash_flow_last_12m": cash_flows,
        "source": source,
    }


def fill_profiles(profiles: list[dict], *, seed: int = 42,
                  scenario: str = "baseline") -> list[dict]:
    """Replace financials in existing complete profiles; keep all other fields."""
    rng = np.random.default_rng(seed)
    result = deepcopy(profiles)
    for index, profile in enumerate(result):
        try:
            company = profile["company"]
            old_financials = profile["financials"]
            as_of = date.fromisoformat(old_financials["as_of_date"])
            registered = date.fromisoformat(company["registration_date"])
            okved = company["okved_main"]
            okved_code = okved["code"] if isinstance(okved, dict) else okved
            profile["financials"] = generate_financials(
                employees_count=company["employees_count"],
                okved_code=okved_code,
                registration_date=registered,
                as_of_date=as_of,
                rng=rng,
                source=old_financials.get("source", "documents"),
                scenario=scenario,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"profiles[{index}]: {exc}") from exc
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic profile financials")
    parser.add_argument("--profiles", required=True, type=Path,
                        help="JSON array of existing complete Borrower Profiles")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario", choices=SCENARIO_NAMES, default="baseline")
    args = parser.parse_args()
    profiles = json.loads(args.profiles.read_text(encoding="utf-8"))
    if not isinstance(profiles, list):
        parser.error("--profiles must contain a JSON array")
    generated = fill_profiles(profiles, seed=args.seed, scenario=args.scenario)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Generated financials for {len(generated)} profiles -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
