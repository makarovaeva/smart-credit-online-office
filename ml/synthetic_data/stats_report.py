"""Descriptive statistics for synthetic SME Borrower Profiles.

Reads the JSON array produced by company.py and writes:
    report.json       machine-readable summary
    report.md         human-readable diagnostics
    features.csv      flattened, non-sensitive, derived numerical features
    plots/*.png       optional plots (requires matplotlib)

This checks distributions and associations, not their realism vs real firms.
It does NOT replace validation.py and never makes a lending decision.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


FEATURES = (
    "employees_count",
    "age_years",
    "annual_turnover_rub",
    "ebitda_rub",
    "ebitda_margin_pct",
    "revenue_change_pct",
    "negative_cf_streak_months",
)

FEATURE_LABELS = (
    "Employees", "Business age", "Turnover", "EBITDA",
    "EBITDA margin", "Revenue change", "Neg. CF streak",
)


class ReportInputError(ValueError):
    """Input does not contain the expected Borrower Profile structure."""


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReportInputError(f"{path}: expected a number, got {type(value).__name__}")
    value = float(value)
    if not math.isfinite(value):
        raise ReportInputError(f"{path}: number must be finite")
    return value


def _field(obj: dict, key: str, path: str) -> Any:
    if key not in obj:
        raise ReportInputError(f"{path}.{key}: missing required field")
    return obj[key]


def longest_negative_streak(flows: list[float]) -> int:
    """Length of the longest CONSECUTIVE sequence of negative monthly flows."""
    best = current = 0
    for value in flows:
        current = current + 1 if value < 0 else 0
        best = max(best, current)
    return best


def extract_rows(profiles: list[dict]) -> list[dict[str, Any]]:
    """Turn nested profiles into descriptive features, fail on missing core data."""
    if not isinstance(profiles, list) or not profiles:
        raise ReportInputError("Expected a non-empty JSON array of Borrower Profiles")

    rows: list[dict[str, Any]] = []
    for i, profile in enumerate(profiles):
        path = f"profiles[{i}]"
        if not isinstance(profile, dict):
            raise ReportInputError(f"{path}: expected a JSON object")
        company = _field(profile, "company", path)
        fin = _field(profile, "financials", path)
        if not isinstance(company, dict) or not isinstance(fin, dict):
            raise ReportInputError(f"{path}: company and financials must be objects")

        employee_raw = _field(company, "employees_count", f"{path}.company")
        if type(employee_raw) is not int or employee_raw < 0:
            raise ReportInputError(f"{path}.company.employees_count: expected nonnegative integer")
        turnover = _number(_field(fin, "annual_turnover", f"{path}.financials"),
                           f"{path}.financials.annual_turnover")
        if turnover < 0:
            raise ReportInputError(f"{path}.financials.annual_turnover: must be >= 0")
        ebitda = _number(_field(fin, "ebitda", f"{path}.financials"),
                         f"{path}.financials.ebitda")
        revenue_change = _number(_field(fin, "revenue_change_pct", f"{path}.financials"),
                                 f"{path}.financials.revenue_change_pct")

        flows = _field(fin, "cash_flow_last_12m", f"{path}.financials")
        if not isinstance(flows, list) or len(flows) != 12:
            raise ReportInputError(f"{path}.financials.cash_flow_last_12m: expected 12 values")
        flows = [_number(v, f"{path}.financials.cash_flow_last_12m[{j}]")
                 for j, v in enumerate(flows)]

        okved = _field(company, "okved_main", f"{path}.company")
        okved_code = okved.get("code", "") if isinstance(okved, dict) else str(okved)
        if not okved_code:
            raise ReportInputError(f"{path}.company.okved_main: missing code")
        try:
            registered = date.fromisoformat(_field(company, "registration_date", f"{path}.company"))
            as_of = date.fromisoformat(_field(fin, "as_of_date", f"{path}.financials"))
        except (ValueError, TypeError) as exc:
            raise ReportInputError(f"{path}: invalid registration_date or financials.as_of_date") from exc
        if registered > as_of:
            raise ReportInputError(f"{path}: registration_date after financials.as_of_date")
        age_years = (as_of - registered).days / 365.2425

        rows.append({
            "borrower_id": str(_field(profile, "borrower_id", path)),
            "legal_form": str(_field(company, "legal_form", f"{path}.company")),
            "region_code": str(_field(company, "region_code", f"{path}.company")),
            "okved_code": str(okved_code),
            "industry_group": str(okved_code).split(".")[0],
            "employees_count": employee_raw,
            "age_years": round(age_years, 4),
            "annual_turnover_rub": turnover,
            "ebitda_rub": ebitda,
            "ebitda_margin_pct": 100 * ebitda / turnover if turnover > 0 else None,
            "revenue_change_pct": revenue_change,
            "net_cash_flow_12m_rub": sum(flows),
            "negative_cf_months": sum(v < 0 for v in flows),
            "negative_cf_streak_months": longest_negative_streak(flows),
        })
    return rows


def describe(values: list[float | int | None]) -> dict[str, float | int | None]:
    """Descriptive stats excluding missing values, no inferential claims."""
    arr = np.array([x for x in values if x is not None], dtype=float)
    if arr.size == 0:
        return {"count": 0, "missing": len(values), "mean": None, "std": None,
                "min": None, "p10": None, "p25": None, "median": None,
                "p75": None, "p90": None, "p99": None, "max": None}
    quantiles = np.quantile(arr, [0.10, 0.25, 0.5, 0.75, 0.90, 0.99])
    return {
        "count": int(arr.size), "missing": len(values) - int(arr.size),
        "mean": round(float(np.mean(arr)), 4),
        "std": round(float(np.std(arr, ddof=1)), 4) if arr.size > 1 else None,
        "min": round(float(np.min(arr)), 4),
        "p10": round(float(quantiles[0]), 4),
        "p25": round(float(quantiles[1]), 4),
        "median": round(float(quantiles[2]), 4),
        "p75": round(float(quantiles[3]), 4),
        "p90": round(float(quantiles[4]), 4),
        "p99": round(float(quantiles[5]), 4),
        "max": round(float(np.max(arr)), 4),
    }


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """Rank values, assigning the average rank to ties (SciPy not required)."""
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(values.size, dtype=float)
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and sorted_values[end] == sorted_values[start]:
            end += 1
        ranks[order[start:end]] = ((start + 1) + end) / 2
        start = end
    return ranks


def spearman(x: list[float | None], y: list[float | None]) -> float | None:
    """Spearman correlation on pairwise non-missing finite observations."""
    paired = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(paired) < 3:
        return None
    a, b = map(lambda z: np.asarray(z, dtype=float), zip(*paired))
    rank_a, rank_b = _average_ranks(a), _average_ranks(b)
    if np.std(rank_a) == 0 or np.std(rank_b) == 0:
        return None
    return round(float(np.corrcoef(rank_a, rank_b)[0, 1]), 4)


def _group_stats(rows: list[dict], field: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(row[field]), []).append(row)
    total = len(rows)
    result = {}
    for key, group in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        n = len(group)
        margin = describe([r["ebitda_margin_pct"] for r in group])
        result[key] = {
            "count": n,
            "share_pct": round(n / total * 100, 2),
            "median_turnover_rub": describe([r["annual_turnover_rub"] for r in group])["median"],
            "median_ebitda_margin_pct": margin["median"],
            "negative_ebitda_pct": round(100 * sum(r["ebitda_rub"] < 0 for r in group) / n, 2),
            "four_plus_negative_cf_streak_pct": round(
                100 * sum(r["negative_cf_streak_months"] >= 4 for r in group) / n, 2
            ),
        }
    return result


def create_report(rows: list[dict], generator_summary: dict | None = None) -> dict:
    if not rows:
        raise ReportInputError("Cannot summarize empty data")
    fields = (
        "employees_count", "age_years", "annual_turnover_rub", "ebitda_rub",
        "ebitda_margin_pct", "revenue_change_pct", "net_cash_flow_12m_rub",
        "negative_cf_months", "negative_cf_streak_months",
    )
    stats = {field: describe([r[field] for r in rows]) for field in fields}
    correlations = {
        a: {b: spearman([r[a] for r in rows], [r[b] for r in rows])
               for b in FEATURES}
        for a in FEATURES
    }
    n = len(rows)
    borrower_ids = [r["borrower_id"] for r in rows]
    warning_messages = [
        "Synthetic sample: these diagnostics do not establish similarity to real Russian SMEs.",
        "No external reference distribution is used; distribution goodness-of-fit is NOT measured.",
        "Company generator omits businesses with <24 completed operating months.",
        "FNS, BKI and compliance fields in company.py are placeholders, not risk observations.",
        "The SME category cannot be recovered reliably from employee count alone.",
    ]
    if len(set(borrower_ids)) < n:
        warning_messages.append("Duplicate borrower_id values detected; run validation.py too.")
    if any(group["count"] < 10 for group in _group_stats(rows, "industry_group").values()):
        warning_messages.append("Some industries have fewer than 10 records; their estimates are unstable.")
    if generator_summary is not None and generator_summary.get("count") != n:
        warning_messages.append("Generator summary count does not equal the input profile count.")
    return {
        "dataset_size": n,
        "descriptive_statistics": stats,
        "rates_pct": {
            "ooo": round(100 * sum(r["legal_form"] == "ooo" for r in rows) / n, 2),
            "ip": round(100 * sum(r["legal_form"] == "ip" for r in rows) / n, 2),
            "zero_employees": round(100 * sum(r["employees_count"] == 0 for r in rows) / n, 2),
            "negative_ebitda": round(100 * sum(r["ebitda_rub"] < 0 for r in rows) / n, 2),
            "revenue_decline": round(100 * sum(r["revenue_change_pct"] < 0 for r in rows) / n, 2),
            "negative_net_cash_flow_12m": round(
                100 * sum(r["net_cash_flow_12m_rub"] < 0 for r in rows) / n, 2
            ),
            "four_plus_consecutive_negative_cf_months": round(
                100 * sum(r["negative_cf_streak_months"] >= 4 for r in rows) / n, 2
            ),
        },
        "by_legal_form": _group_stats(rows, "legal_form"),
        "by_industry": _group_stats(rows, "industry_group"),
        "by_region": _group_stats(rows, "region_code"),
        "spearman_correlations": correlations,
        "feature_names": list(FEATURES),
        "generator_summary": generator_summary,
        "warnings": warning_messages,
    }


def _fmt(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}".replace(",", " ")


def render_markdown(report: dict) -> str:
    st = report["descriptive_statistics"]
    rates = report["rates_pct"]
    lines = [
        "# Отчёт о синтетических данных ММБ",
        "",
        f"Объём выборки: **{report['dataset_size']:,}** профилей.",
        "",
        "> Это описательный анализ синтетической выборки, а не подтверждение её реалистичности.",
        "",
        "## Ключевые показатели",
        "",
        "| Показатель | Значение |",
        "|---|---:|",
        f"| Медианный годовой оборот, ₽ | {_fmt(st['annual_turnover_rub']['median'], 0)} |",
        f"| P90 годового оборота, ₽ | {_fmt(st['annual_turnover_rub']['p90'], 0)} |",
        f"| Медианная EBITDA margin, % | {_fmt(st['ebitda_margin_pct']['median'])} |",
        f"| Медианное число сотрудников | {_fmt(st['employees_count']['median'])} |",
        f"| Компании с отрицательной EBITDA | {rates['negative_ebitda']}% |",
        f"| Компании с падением выручки | {rates['revenue_decline']}% |",
        f"| Компании с >=4 подряд отрицательными CF-месяцами | {rates['four_plus_consecutive_negative_cf_months']}% |",
        f"| Компании без сотрудников | {rates['zero_employees']}% |",
        "",
        "## Распределения (описательная статистика)",
        "",
        "| Признак | Min | P10 | Median | P90 | P99 | Max |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for feature in st:
        v = st[feature]
        lines.append(
            f"| `{feature}` | {_fmt(v['min'])} | {_fmt(v['p10'])} | "
            f"{_fmt(v['median'])} | {_fmt(v['p90'])} | {_fmt(v['p99'])} | {_fmt(v['max'])} |"
        )

    for title, key in (("Юридическая форма", "by_legal_form"),
                       ("Отрасли (код ОКВЭД)", "by_industry")):
        lines.extend([
            "", f"## {title}", "",
            "| Группа | N | Доля | Median turnover, ₽ | Median EBITDA margin, % | EBITDA < 0, % | CF streak >=4, % |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ])
        for label, v in report[key].items():
            lines.append(
                f"| {label} | {v['count']} | {v['share_pct']}% | "
                f"{_fmt(v['median_turnover_rub'], 0)} | {_fmt(v['median_ebitda_margin_pct'])} | "
                f"{v['negative_ebitda_pct']}% | {v['four_plus_negative_cf_streak_pct']}% |"
            )

    lines.extend(["", "## Spearman: ранговая корреляция", "",
                  "Коэффициент от −1 до 1 описывает монотонную связь, а не причинность.", "",
                  "| Признак | " + " | ".join(FEATURES) + " |",
                  "|---|" + "---:|" * len(FEATURES)])
    for name in FEATURES:
        lines.append("| `" + name + "` | " + " | ".join(
            _fmt(report["spearman_correlations"][name][other], 2) for other in FEATURES
        ) + " |")
    lines.extend(["", "## Ограничения и предупреждения", ""])
    for warning in report["warnings"]:
        lines.append(f"- {warning}")
    if report["generator_summary"] is not None:
        lines.extend(["", "## Параметры запуска генератора", "", "```json",
                      json.dumps(report["generator_summary"], ensure_ascii=False, indent=2),
                      "```"])
    lines.append("")
    return "\n".join(lines)


def make_plots(rows: list[dict], report: dict, plots_dir: Path) -> list[str]:
    """Save separate PNG figures. Import matplotlib only when plotting is requested."""
    import matplotlib
    matplotlib.use("Agg")  # works headlessly (e.g., CI)
    import matplotlib.pyplot as plt

    plots_dir.mkdir(parents=True, exist_ok=True)
    produced = []

    def save(fig: Any, name: str) -> None:
        fig.tight_layout()
        fig.savefig(plots_dir / name, dpi=150)
        plt.close(fig)
        produced.append(f"plots/{name}")

    turnovers = np.asarray([r["annual_turnover_rub"] for r in rows], dtype=float)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.hist(np.log10(turnovers + 1), bins=min(35, max(6, int(np.sqrt(len(rows))))))
    ax.set(xlabel="log10(Annual turnover + 1 RUB)", ylabel="Companies",
           title="Distribution of annual turnover (log scale)")
    save(fig, "turnover_log_hist.png")

    margins = [r["ebitda_margin_pct"] for r in rows if r["ebitda_margin_pct"] is not None]
    if margins:
        fig, ax = plt.subplots(figsize=(8, 4.8))
        ax.hist(margins, bins=min(35, max(6, int(np.sqrt(len(margins))))))
        ax.axvline(0, linestyle="--", linewidth=1)
        ax.set(xlabel="EBITDA margin (%)", ylabel="Companies",
               title="EBITDA profitability")
        save(fig, "ebitda_margin_hist.png")

    bucket_names = ("0", "1", "2–5", "6–15", "16–50", "51–100", ">100")
    bucket_counts = Counter()
    for row in rows:
        e = row["employees_count"]
        bucket = ("0" if e == 0 else "1" if e == 1 else "2–5" if e <= 5
                  else "6–15" if e <= 15 else "16–50" if e <= 50
                  else "51–100" if e <= 100 else ">100")
        bucket_counts[bucket] += 1
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar(bucket_names, [bucket_counts[b] for b in bucket_names])
    ax.set(xlabel="Employees per business", ylabel="Companies",
           title="Employee count by size band")
    save(fig, "employees_bands.png")

    streak = Counter(r["negative_cf_streak_months"] for r in rows)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar(list(range(13)), [streak.get(v, 0) for v in range(13)])
    ax.set(xlabel="Longest consecutive negative-CF run (months)", ylabel="Companies",
           title="Cash-flow stress", xticks=list(range(13)))
    save(fig, "negative_cf_streak.png")

    matrix = np.array([
        [report["spearman_correlations"][a][b]
         if report["spearman_correlations"][a][b] is not None else np.nan
         for b in FEATURES]
        for a in FEATURES
    ], dtype=float)
    fig, ax = plt.subplots(figsize=(9, 7.8))
    cmap = plt.get_cmap("coolwarm").copy()
    cmap.set_bad("lightgray")
    im = ax.imshow(np.ma.masked_invalid(matrix), vmin=-1, vmax=1, cmap=cmap)
    ax.set_xticks(range(len(FEATURES)), labels=FEATURE_LABELS, rotation=45, ha="right")
    ax.set_yticks(range(len(FEATURES)), labels=FEATURE_LABELS)
    for i in range(len(FEATURES)):
        for j in range(len(FEATURES)):
            if np.isfinite(matrix[i, j]):
                ax.text(j, i, f"{matrix[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="Spearman rho")
    ax.set_title("Rank correlations among synthetic features")
    save(fig, "spearman_heatmap.png")
    return produced


def write_report(profiles: list[dict], out_dir: Path, *,
                 generator_summary: dict | None = None, plots: bool = True) -> dict:
    rows = extract_rows(profiles)
    report = create_report(rows, generator_summary)
    out_dir.mkdir(parents=True, exist_ok=True)

    features_path = out_dir / "features.csv"
    with features_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    report["plots"] = []
    if plots:
        try:
            report["plots"] = make_plots(rows, report, out_dir / "plots")
        except ImportError as exc:
            report["warnings"].append(
                f"Plots skipped ({exc}); install matplotlib or use --no-plots."
            )
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Statistical diagnostics of synthetic SME profiles")
    parser.add_argument("--profiles", required=True, type=Path, help="company.py JSON output")
    parser.add_argument("--out-dir", required=True, type=Path, help="folder for report and charts")
    parser.add_argument("--generator-summary", type=Path,
                        help="optional company.py --summary-out JSON")
    parser.add_argument("--no-plots", action="store_true", help="do not require matplotlib")
    args = parser.parse_args()
    try:
        profiles = json.loads(args.profiles.read_text(encoding="utf-8-sig"))
        summary = (json.loads(args.generator_summary.read_text(encoding="utf-8-sig"))
                   if args.generator_summary else None)
        report = write_report(profiles, args.out_dir, generator_summary=summary,
                              plots=not args.no_plots)
    except (OSError, json.JSONDecodeError, ReportInputError) as exc:
        parser.exit(status=2, message=f"Input error: {exc}\n")
    print(f"Processed {report['dataset_size']} profiles. Files saved in {args.out_dir}")
    print(f"Median turnover: {report['descriptive_statistics']['annual_turnover_rub']['median']:,.0f} RUB")
    print(f"Negative EBITDA: {report['rates_pct']['negative_ebitda']}%")
    print(f"4+ consecutive negative CF months: "
          f"{report['rates_pct']['four_plus_consecutive_negative_cf_months']}%")
    print(f"Charts created: {len(report['plots'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
