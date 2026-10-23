"""Unit tests of descriptive statistics, run with unittest discovery."""
import json
from pathlib import Path
import tempfile
import unittest

from stats_report import (
    ReportInputError, create_report, describe, extract_rows,
    longest_negative_streak, spearman, write_report,
)


class StatsReportTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "borrower_id": "brw_1",
            "company": {
                "legal_form": "ooo", "employees_count": 4,
                "region_code": "77", "okved_main": {"code": "62.01"},
                "registration_date": "2020-01-01",
            },
            "financials": {
                "as_of_date": "2026-09-30", "annual_turnover": 10_000_000,
                "ebitda": 2_000_000, "revenue_change_pct": -10.0,
                "cash_flow_last_12m": [100, -2, -3, -4, 1, -6, -7, 3, 4, 5, 6, 7],
            },
        }

    def test_streak_counts_consecutive_months(self):
        self.assertEqual(longest_negative_streak([1, -2, -3, 1, -4]), 2)
        self.assertEqual(longest_negative_streak([0] * 12), 0)

    def test_profile_features(self):
        row = extract_rows([self.profile])[0]
        self.assertAlmostEqual(row["ebitda_margin_pct"], 20.0)
        self.assertEqual(row["negative_cf_streak_months"], 3)
        self.assertEqual(row["negative_cf_months"], 5)
        self.assertEqual(row["industry_group"], "62")
        self.assertGreater(row["age_years"], 6)

    def test_report_shares(self):
        rows = extract_rows([self.profile])
        report = create_report(rows)
        self.assertEqual(report["dataset_size"], 1)
        self.assertEqual(report["rates_pct"]["revenue_decline"], 100)
        self.assertEqual(report["rates_pct"]["negative_ebitda"], 0)
        self.assertEqual(report["rates_pct"]["four_plus_consecutive_negative_cf_months"], 0)

    def test_constant_correlation_is_undefined(self):
        self.assertIsNone(spearman([1, 1, 1], [1, 2, 3]))
        self.assertEqual(spearman([1, 2, 3], [5, 6, 7]), 1.0)
        self.assertEqual(spearman([1, 2, 3], [7, 6, 5]), -1.0)

    def test_describe_missing(self):
        summary = describe([None, 10, 20])
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(summary["median"], 15.0)

    def test_bad_cashflows_fail_early(self):
        bad = json.loads(json.dumps(self.profile))
        bad["financials"]["cash_flow_last_12m"] = [1, 2]
        with self.assertRaisesRegex(ReportInputError, "12 values"):
            extract_rows([bad])

    def test_reports_written_without_matplotlib(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            report = write_report([self.profile], out, plots=False)
            self.assertTrue((out / "report.json").is_file())
            self.assertTrue((out / "report.md").is_file())
            self.assertTrue((out / "features.csv").is_file())
            self.assertEqual(report["plots"], [])
            saved = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["dataset_size"], 1)


if __name__ == "__main__":
    unittest.main()
