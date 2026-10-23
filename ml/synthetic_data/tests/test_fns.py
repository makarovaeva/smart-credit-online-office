"""Tests for standalone synthetic FNS/registration enrichment."""
import unittest
from copy import deepcopy
from datetime import date

import numpy as np

from company import generate_profiles
from bki import fill_profiles as fill_bki
from fns import fill_profiles, generate_fns_data, summarize, validate_fns_data
from validation import validate_dataset


class FNSGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        companies, _ = generate_profiles(1200, seed=42, as_of_date=date(2026, 9, 30))
        cls.profiles = fill_bki(companies, seed=43)

    def test_deterministic(self):
        src = self.profiles[:50]
        self.assertEqual(fill_profiles(src, seed=44), fill_profiles(src, seed=44))
        self.assertNotEqual(fill_profiles(src, seed=44), fill_profiles(src, seed=45))

    def test_only_fns_data_changes(self):
        original = deepcopy(self.profiles[:30])
        result = fill_profiles(original)
        self.assertEqual(original, self.profiles[:30])
        for before, after in zip(original, result):
            for field in before:
                if field != "fns_data":
                    self.assertEqual(before[field], after[field])
            self.assertEqual(before["fns_data"]["retrieved_at"], after["fns_data"]["retrieved_at"])
            self.assertEqual(before["fns_data"]["has_account_block_115fz"],
                             after["fns_data"]["has_account_block_115fz"])

    def test_schema_and_project_validator(self):
        result = fill_profiles(self.profiles, seed=44)
        for profile in result:
            validate_fns_data(profile["fns_data"], legal_form=profile["company"]["legal_form"])
        self.assertTrue(validate_dataset(result, applications=[], assessments=[]).passed)

    def test_some_bad_cases(self):
        result = fill_profiles(self.profiles, seed=44, scenario="demo")
        self.assertTrue(any(p["fns_data"]["bankruptcy_status"] != "none" for p in result))
        self.assertTrue(any(p["fns_data"]["tax_arrears_amount"] > 0 for p in result))
        self.assertTrue(any(p["fns_data"]["is_mass_address"] for p in result))
        self.assertTrue(any(not p["fns_data"]["has_tax_activity"] for p in result))

    def test_ip_no_corporate_flags(self):
        result = fill_profiles(self.profiles, seed=44, scenario="demo")
        for p in result:
            if p["company"]["legal_form"] == "ip":
                f = p["fns_data"]
                self.assertFalse(f["is_mass_address"])
                self.assertFalse(f["is_mass_director"])
                self.assertNotEqual(f["bankruptcy_status"], "observation")
                self.assertNotEqual(f["egrul_status"], "liquidating")

    def test_negative_debt_rejected(self):
        f = deepcopy(self.profiles[0]["fns_data"])
        f["tax_arrears_amount"] = -100
        with self.assertRaisesRegex(ValueError, "tax_arrears_amount"):
            validate_fns_data(f)

    def test_invalid_timestamp_rejected(self):
        p = deepcopy(self.profiles[0])
        p["fns_data"]["retrieved_at"] = "not-a-time"
        with self.assertRaisesRegex(ValueError, "retrieved_at"):
            generate_fns_data(p, rng=np.random.default_rng(2))

    def test_duplicate_id_rejected(self):
        p = deepcopy(self.profiles[0])
        with self.assertRaisesRegex(ValueError, "duplicate borrower_id"):
            fill_profiles([p, deepcopy(p)])

    def test_existing_compliance_flag_preserved(self):
        p = deepcopy(self.profiles[0])
        p["fns_data"]["has_account_block_115fz"] = True
        result = fill_profiles([p])
        self.assertTrue(result[0]["fns_data"]["has_account_block_115fz"])
        self.assertTrue(result[0]["compliance"] == p["compliance"])

    def test_summary_consistent(self):
        result = fill_profiles(self.profiles[:100])
        stats = summarize(result, seed=44, scenario="baseline")
        self.assertEqual(sum(stats["egrul_status_counts"].values()), 100)
        self.assertEqual(sum(stats["bankruptcy_counts"].values()), 100)


if __name__ == "__main__":
    unittest.main()
