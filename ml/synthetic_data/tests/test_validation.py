"""Tests for semantic data validation. Read fixed reference JSON fixtures."""

import copy
import json
import unittest
from pathlib import Path

from validation import longest_negative_streak, validate_dataset

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def fixtures():
    return tuple(json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
                 for name in ("profiles.json", "applications.json", "assessments.json"))


class ValidatorTests(unittest.TestCase):
    def test_contract_examples_are_consistent(self):
        self.assertTrue(validate_dataset(*fixtures()).passed)

    def test_wrong_dscr_is_detected(self):
        p, a, s = fixtures()
        s[0]["metrics"]["dscr"] = 0.5
        report = validate_dataset(p, a, s)
        self.assertFalse(report.passed)
        self.assertTrue(any(i.path.endswith("metrics.dscr") for i in report.issues))

    def test_incomplete_cash_flow_is_detected(self):
        p, a, s = fixtures()
        p[0]["financials"]["cash_flow_last_12m"] = [100, 200]
        report = validate_dataset(p, a, s)
        self.assertTrue(any("cash_flow_last_12m" in i.path for i in report.issues))

    def test_invalid_foreign_key_is_detected(self):
        p, a, s = fixtures()
        a[0]["borrower_id"] = "brw_missing"
        report = validate_dataset(p, a, s)
        self.assertTrue(any(i.path.endswith("borrower_id") for i in report.issues))

    def test_stop_factor_must_match_rule(self):
        p, a, s = fixtures()
        check = next(x for x in s[0]["stop_factor_checks"] if x["code"] == "dscr_below_0_9")
        check["triggered"] = True  # But DSCR is 2.13
        report = validate_dataset(p, a, s)
        self.assertFalse(report.passed)
        self.assertTrue(any("Incorrect flag" in i.message for i in report.issues))

    def test_consecutive_negative_months(self):
        values = [5, -1, -2, 0, -3, -4, -5, 1, 2, 3, 4, 5]
        self.assertEqual(longest_negative_streak(values), 3)


if __name__ == "__main__":
    unittest.main()
