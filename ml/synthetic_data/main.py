"""Run the COMPLETE synthetic Borrower → Application → Assessment pipeline.

Uses the existing generators as Python modules. Inputs stay in memory until
semantic validation passes. Distinct outputs are written to --out-dir.

Run from repository root:
  uv run --project backend --group ml python ml/synthetic_data/main.py \
    --count 1200 --seed 42 --scenario baseline \
    --out-dir ml/synthetic_data/data/run_001

--overwrite explicitly replaces files in that directory. Individual stage
scripts still work independently for debugging.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any

import company
import bki
import fns
import compliance
import applications
import assessment
import sanity_check
import validation


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding="utf-8")


def run_pipeline(*, count: int = 1200, seed: int = 42,
                 as_of: date = date(2026, 9, 30), scenario: str = "baseline",
                 mix: str = "population", application_rate: float = 1.0,
                 mock_confidence_pct: float = 90.0) -> dict:
    """One deterministic generation run without modifying any files."""
    if scenario not in ("baseline", "stress_2025", "demo"):
        raise ValueError("scenario must be baseline, stress_2025, or demo")
    # Different generators support different scenario choices. In demo mode,
    # stress is NOT automatically enabled in company/BKI; demos amplify cases
    # only for modules that explicitly implement demo probabilities.
    company_scenario = "baseline" if scenario == "demo" else scenario
    bki_scenario = "baseline" if scenario == "demo" else scenario
    fns_scenario = scenario
    compliance_scenario = scenario
    app_scenario = "demo" if scenario == "demo" else "baseline"

    profiles_companies, company_summary = company.generate_profiles(
        count, seed=seed, as_of_date=as_of, mix=mix, scenario=company_scenario)
    profiles_bki = bki.fill_profiles(profiles_companies, seed=seed+1, scenario=bki_scenario)
    profiles_fns = fns.fill_profiles(profiles_bki, seed=seed+2, scenario=fns_scenario)
    profiles_compliance = compliance.fill_profiles(profiles_fns, seed=seed+3,
                                                   scenario=compliance_scenario)
    apps, app_summary = applications.generate_applications(
        profiles_compliance, seed=seed+4, scenario=app_scenario,
        application_rate=application_rate)
    assessments, apps_assessed, assessment_summary = assessment.assess_applications(
        profiles_compliance, apps, mock_confidence_pct=mock_confidence_pct)
    report = validation.validate_dataset(profiles_compliance, apps_assessed, assessments)
    if not report.passed:
        first = [i.__dict__ for i in report.issues if i.level == "error"][:4]
        raise ValueError(f"Generated data failed semantic validation: {first}")

    metadata = {
        "scenario_requested": scenario,
        "module_scenarios": {"company_financials": company_scenario,
                             "bki": bki_scenario, "fns": fns_scenario,
                             "compliance": compliance_scenario, "applications": app_scenario},
        "count": count, "seed": seed, "as_of": as_of.isoformat(), "mix": mix,
        "application_rate": application_rate,
        "company": company_summary,
        "bki": bki.summarize(profiles_bki, seed=seed+1, scenario=bki_scenario),
        "fns": fns.summarize(profiles_fns, seed=seed+2, scenario=fns_scenario),
        "compliance": compliance.summarize(profiles_compliance, seed=seed+3,
                                           scenario=compliance_scenario),
        "applications": app_summary, "assessment": assessment_summary,
        "note": "Synthetic demonstration data; not calibrated default probabilities or bank approvals",
    }
    return {
        "profiles_companies": profiles_companies,
        "profiles_bki": profiles_bki,
        "profiles_fns": profiles_fns,
        "profiles_compliance": profiles_compliance,
        "applications_generated": apps,
        "applications_assessed": apps_assessed,
        "assessments_generated": assessments,
        "quality_report": report.to_dict(),
        "sanity_report": sanity_check.audit(profiles_compliance),
        "run_metadata": metadata,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the entire synthetic MMB credit pipeline")
    parser.add_argument("--count", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--scenario", choices=("baseline", "stress_2025", "demo"), default="baseline")
    parser.add_argument("--mix", choices=("population", "demo"), default="population")
    parser.add_argument("--application-rate", type=float, default=1.0)
    parser.add_argument("--mock-confidence-pct", type=float, default=90.0)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--stats", action="store_true", help="also create CSV/Markdown/plots (matplotlib optional)")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    names = ("profiles_companies", "profiles_bki", "profiles_fns", "profiles_compliance",
             "applications_generated", "applications_assessed", "assessments_generated",
             "quality_report", "sanity_report", "run_metadata")
    outputs = [args.out_dir / f"{name}.json" for name in names]
    existing = [p for p in outputs if p.exists()]
    if args.stats and (args.out_dir / "stats_report").exists():
        existing.append(args.out_dir / "stats_report")
    if existing and not args.overwrite:
        parser.error(f"Outputs already exist (e.g. {existing[0]}). Use --overwrite or a new --out-dir")
    try:
        results = run_pipeline(
            count=args.count, seed=args.seed, as_of=args.as_of,
            scenario=args.scenario, mix=args.mix,
            application_rate=args.application_rate,
            mock_confidence_pct=args.mock_confidence_pct)
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        parser.error(str(exc))
    # Only write after complete core validation.
    for name in names:
        _write_json(args.out_dir / f"{name}.json", results[name])
    if args.stats:
        import stats_report
        stats_report.write_report(results["profiles_compliance"], args.out_dir / "stats_report",
                                  generator_summary=results["run_metadata"]["company"])
    quality = results["quality_report"]
    routes = results["run_metadata"]["assessment"]["route_counts"]
    print(f"Generated {len(results['profiles_compliance'])} companies, "
          f"{len(results['applications_assessed'])} applications and "
          f"{len(results['assessments_generated'])} assessments")
    print(f"Routes: {routes}")
    print(f"Validation: passed={quality['passed']}; errors={quality['errors']}; "
          f"warnings={quality['warnings']}")
    print(f"Results: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
