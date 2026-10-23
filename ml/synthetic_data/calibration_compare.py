"""Compare hypothetical financial scenarios on reproducible synthetic data.

This is scenario/sensitivity analysis, NOT empirical calibration to actual SME
credit losses. Run from ml/synthetic_data or with python path to this script.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

from company import generate_profiles
from financials import SCENARIO_NAMES


def _max_negative_run(flows: list[int]) -> int:
    longest = current = 0
    for value in flows:
        current = current + 1 if value < 0 else 0
        longest = max(longest, current)
    return longest


def summarize(profiles: list[dict]) -> dict:
    """Observed descriptive measures for ONE sample, not population truth."""
    n = len(profiles)
    if not n:
        raise ValueError("Profiles cannot be empty")
    financials = [profile["financials"] for profile in profiles]
    companies = [profile["company"] for profile in profiles]
    margins = np.asarray([
        f["ebitda"] / f["annual_turnover"] * 100
        for f in financials
    ])
    growth = np.asarray([f["revenue_change_pct"] for f in financials])
    turnover = np.asarray([f["annual_turnover"] for f in financials])
    runs = np.asarray([_max_negative_run(f["cash_flow_last_12m"]) for f in financials])
    ooo = [c for c in companies if c["legal_form"] == "ooo"]
    ip = [c for c in companies if c["legal_form"] == "ip"]
    return {
        "n": n,
        "segment_mix": dict(sorted(Counter(c["legal_form"] for c in companies).items())),
        "median_turnover_rub": round(float(np.median(turnover))),
        "negative_ebitda_pct": round(float(np.mean(margins < 0) * 100), 2),
        "median_ebitda_margin_pct": round(float(np.median(margins)), 2),
        "p90_ebitda_margin_pct": round(float(np.quantile(margins, 0.90)), 2),
        "p99_ebitda_margin_pct": round(float(np.quantile(margins, 0.99)), 2),
        "declining_revenue_pct": round(float(np.mean(growth < 0) * 100), 2),
        "median_revenue_growth_pct": round(float(np.median(growth)), 2),
        "four_plus_negative_cf_months_pct": round(float(np.mean(runs >= 4) * 100), 2),
        "zero_employees_ooo_pct": round(100 * sum(c["employees_count"] == 0 for c in ooo) / len(ooo), 2) if ooo else None,
        "zero_employees_ip_pct": round(100 * sum(c["employees_count"] == 0 for c in ip) / len(ip), 2) if ip else None,
    }


def compare(count: int = 1200, seed: int = 42,
            as_of: date = date(2026, 9, 30),
            mix: str = "population") -> dict:
    result = {
        "metadata": {
            "count": count, "seed": seed, "as_of": as_of.isoformat(),
            "mix": mix,
            "methodology": "Hypothetical scenario sensitivity, NOT statistical fit to population or default rates",
        },
        "scenarios": {},
    }
    for name in SCENARIO_NAMES:
        profiles, _metadata = generate_profiles(
            count, seed=seed, as_of_date=as_of, mix=mix, scenario=name
        )
        result["scenarios"][name] = summarize(profiles)
    return result


def markdown(report: dict) -> str:
    keys = [
        ("negative_ebitda_pct", "EBITDA < 0, %"),
        ("declining_revenue_pct", "Выручка падает, %"),
        ("four_plus_negative_cf_months_pct", "Cash flow < 0: 4+ мес. подряд, %"),
        ("median_ebitda_margin_pct", "Медианная EBITDA margin, %"),
        ("p99_ebitda_margin_pct", "EBITDA margin P99, %"),
        ("median_turnover_rub", "Медианный оборот, ₽"),
        ("zero_employees_ooo_pct", "ООО без работников, %"),
    ]
    scenarios = report["scenarios"]
    names = ["legacy_v01", "baseline", "stress_2025"]
    lines = [
        "# Проверка финансовых сценариев",
        "",
        f"N={report['metadata']['count']}, seed={report['metadata']['seed']}, "
        f"as_of={report['metadata']['as_of']}, mix={report['metadata']['mix']}.",
        "",
        "**Важно:** это сравнение гипотез генератора, а не оценка сходства с российской ",
        "статистикой МСП. Ни один процент не следует называть частотой дефолтов.",
        "",
        "| Показатель | v0.1 | baseline | stress_2025 |",
        "|---|---:|---:|---:|",
    ]
    for key, label in keys:
        values = [scenarios[name][key] for name in names]
        lines.append("| " + label + " | " + " | ".join(str(x) for x in values) + " |")
    lines.extend([
        "",
        "## Интерпретация",
        "",
        "- baseline: искусственно выбранный нейтральный сценарий для функционального MVP",
        "- stress_2025: **условный** стрессовый сценарий, а не восстановленная популяция 2025 года",
        "- legacy_v01: исходная модель для контроля влияния новых коэффициентов",
        "- Изменение долей может зависеть также от состава фирм и случайного seed",
        "- Данные БКИ/ФНС по-прежнему заглушки; молодые компании младше 24 полных месяцев не включены",
        "- Для настоящей калибровки требуются сопоставимые первичные данные (периметр, период, определение метрик)",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Compare illustrative financial scenarios")
    p.add_argument("--count", type=int, default=1200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 9, 30))
    p.add_argument("--mix", choices=("population", "demo"), default="population")
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    report = compare(args.count, seed=args.seed, as_of=args.as_of, mix=args.mix)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "calibration_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out_dir / "calibration_comparison.md").write_text(
        markdown(report), encoding="utf-8"
    )
    print(markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
