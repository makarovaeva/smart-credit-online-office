"""Regression tests for the v0.2 scenario parameterization."""
import unittest
from datetime import date

from calibration_compare import compare, summarize
from company import generate_profiles
from financials import SCENARIO_NAMES
from validation import validate_dataset


class CalibrationTests(unittest.TestCase):
    def test_scenarios_supported(self):
        self.assertEqual(set(SCENARIO_NAMES), {"baseline", "stress_2025", "legacy_v01"})
        with self.assertRaises(ValueError):
            generate_profiles(5, scenario="not-a-scenario")

    def test_each_scenario_valid_and_deterministic(self):
        for scenario in SCENARIO_NAMES:
            with self.subTest(scenario=scenario):
                a, _ = generate_profiles(50, seed=42, scenario=scenario)
                b, _ = generate_profiles(50, seed=42, scenario=scenario)
                self.assertEqual(a, b)
                self.assertTrue(validate_dataset(a, []).passed)
                self.assertEqual(len(a), 50)
                self.assertEqual(len(a[0]["financials"]["cash_flow_last_12m"]), 12)

    def test_baseline_zero_employee_ooo_avoided(self):
        profiles, _ = generate_profiles(500, seed=12, scenario="baseline")
        for p in profiles:
            if p["company"]["legal_form"] == "ooo":
                self.assertGreaterEqual(p["company"]["employees_count"], 1)

    def test_stress_is_more_distressed_in_demo_sample(self):
        neutral, _ = generate_profiles(1200, seed=42, scenario="baseline")
        stressed, _ = generate_profiles(1200, seed=42, scenario="stress_2025")
        base = summarize(neutral)
        stress = summarize(stressed)
        self.assertGreater(stress["negative_ebitda_pct"], base["negative_ebitda_pct"])
        self.assertGreater(stress["declining_revenue_pct"], base["declining_revenue_pct"])
        self.assertGreater(stress["four_plus_negative_cf_months_pct"],
                           base["four_plus_negative_cf_months_pct"])

    def test_comparison_has_three_scenarios(self):
        report = compare(25, seed=11, as_of=date(2026, 9, 30))
        self.assertEqual(len(report["scenarios"]), 3)
        self.assertEqual(report["scenarios"]["baseline"]["n"], 25)


if __name__ == "__main__":
    unittest.main()
