"""Tests for the financial generator. Run discovery from synthetic_data/."""
import json
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

import numpy as np

from financials import fill_profiles, generate_financials, last_closed_month
from validation import validate_dataset

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class FinancialGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = json.loads((FIXTURES_DIR / "profiles.json").read_text(encoding="utf-8"))
        cls.apps = json.loads((FIXTURES_DIR / "applications.json").read_text(encoding="utf-8"))

    def test_month_end(self):
        self.assertEqual(last_closed_month(date(2026, 10, 23)), (2026, 9))
        self.assertEqual(last_closed_month(date(2026, 9, 30)), (2026, 9))

    def test_reproducibility(self):
        a = fill_profiles(self.profiles, seed=42)
        b = fill_profiles(self.profiles, seed=42)
        c = fill_profiles(self.profiles, seed=43)
        self.assertEqual(a, b)
        self.assertNotEqual(a[0]["financials"], c[0]["financials"])

    def test_preserves_input_and_other_fields(self):
        original = deepcopy(self.profiles)
        out = fill_profiles(self.profiles, seed=42)
        self.assertEqual(self.profiles, original)
        self.assertEqual(out[0]["company"], original[0]["company"])
        self.assertEqual(out[0]["bki_data"], original[0]["bki_data"])

    def test_generated_profiles_pass_previous_validator(self):
        out = fill_profiles(self.profiles, seed=42)
        report = validate_dataset(out, self.apps, assessments=[])
        self.assertTrue(report.passed, report.to_dict())
        f = out[0]["financials"]
        self.assertEqual(len(f["cash_flow_last_12m"]), 12)
        self.assertGreater(f["annual_turnover"], 0)

    def test_young_company_raises_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "24 completed"):
            generate_financials(employees_count=3, okved_code="62.01",
                                registration_date=date(2026, 5, 1),
                                as_of_date=date(2026, 9, 30),
                                rng=np.random.default_rng(42))

    def test_partial_registration_month_does_not_count(self):
        with self.assertRaisesRegex(ValueError, "24 completed"):
            generate_financials(employees_count=3, okved_code="62.01",
                                registration_date=date(2024, 10, 15),
                                as_of_date=date(2026, 9, 30),
                                rng=np.random.default_rng(42))

    def test_no_invalid_workers(self):
        with self.assertRaises(ValueError):
            generate_financials(employees_count=-1, okved_code="62.01",
                                registration_date=date(2019, 1, 1),
                                as_of_date=date(2026, 9, 30),
                                rng=np.random.default_rng(42))


if __name__ == "__main__":
    unittest.main()
