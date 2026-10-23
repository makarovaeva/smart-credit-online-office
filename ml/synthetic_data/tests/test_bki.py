"""Unit and integration tests for synthetic BKI enrichment."""
import json
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

import numpy as np

from bki import (
    fill_profiles, financial_stress_proxy, generate_bki_data,
    summarize, validate_bki_data,
)
from company import generate_profiles
from validation import validate_dataset

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class BKIGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles, _ = generate_profiles(1200, seed=42, as_of_date=date(2026, 9, 30))

    def test_seed_reproducibility(self):
        original = self.profiles[:40]
        self.assertEqual(fill_profiles(original, seed=43), fill_profiles(original, seed=43))
        self.assertNotEqual(fill_profiles(original, seed=43), fill_profiles(original, seed=44))

    def test_input_and_financials_remain_unchanged(self):
        original = deepcopy(self.profiles[:20])
        result = fill_profiles(original, seed=43)
        self.assertEqual(original, self.profiles[:20])
        for before, after in zip(original, result):
            self.assertEqual(before["borrower_id"], after["borrower_id"])
            self.assertEqual(before["company"], after["company"])
            self.assertEqual(before["financials"], after["financials"])
            self.assertEqual(before["fns_data"], after["fns_data"])

    def test_generated_records_obey_invariants(self):
        result = fill_profiles(self.profiles, seed=43)
        for p in result:
            validate_bki_data(p["bki_data"])
        self.assertTrue(validate_dataset(result, applications=[], assessments=[]).passed)

    def test_all_quality_categories_appear(self):
        result = fill_profiles(self.profiles, seed=43)
        qualities = {p["bki_data"]["credit_history_quality"] for p in result}
        self.assertEqual(qualities, {"good", "weak", "none"})

    def test_zero_balance_with_past_good_credit_is_allowed(self):
        validate_bki_data({
            "credit_history_quality": "good", "active_loans_count": 0,
            "total_debt_amount": 0, "monthly_debt_service": 0,
            "overdue_amount": 0, "max_overdue_days_12m": 0,
        })

    def test_inconsistent_overdue_rejected(self):
        with self.assertRaisesRegex(ValueError, "Overdue amount"):
            validate_bki_data({
                "credit_history_quality": "weak", "active_loans_count": 1,
                "total_debt_amount": 100, "monthly_debt_service": 10,
                "overdue_amount": 101, "max_overdue_days_12m": 30,
            })

    def test_stress_proxy_monotonicity(self):
        profile = deepcopy(self.profiles[0])
        base = financial_stress_proxy(profile)
        profile["financials"]["ebitda"] = -profile["financials"]["annual_turnover"]
        profile["financials"]["revenue_change_pct"] = -40
        profile["financials"]["cash_flow_last_12m"] = [-1] * 12
        self.assertGreaterEqual(financial_stress_proxy(profile), base)

    def test_stats_sum(self):
        result = fill_profiles(self.profiles[:100], seed=43)
        stats = summarize(result, seed=43, scenario="baseline")
        self.assertEqual(sum(stats["quality_counts"].values()), 100)

    def test_duplicate_borrower_id_rejected(self):
        p = deepcopy(self.profiles[0])
        with self.assertRaisesRegex(ValueError, "Duplicate borrower_id"):
            fill_profiles([p, deepcopy(p)])

    def test_nonpositive_turnover_rejected(self):
        p = deepcopy(self.profiles[0])
        p["financials"]["annual_turnover"] = 0
        with self.assertRaisesRegex(ValueError, "annual_turnover"):
            generate_bki_data(p, rng=np.random.default_rng(3))


if __name__ == "__main__":
    unittest.main()
