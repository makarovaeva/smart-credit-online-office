"""Unit/integration tests for synthetic compliance enrichment."""
import unittest
from copy import deepcopy
from datetime import date

import numpy as np

from bki import fill_profiles as fill_bki
from company import generate_profiles
from compliance import (fill_profiles, generate_compliance_data,
                        summarize, validate_compliance_profile)
from fns import fill_profiles as fill_fns
from validation import validate_dataset


class ComplianceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profiles, _ = generate_profiles(1200, seed=42, as_of_date=date(2026, 9, 30))
        profiles = fill_bki(profiles, seed=43)
        cls.profiles = fill_fns(profiles, seed=44)

    def test_seed_determinism(self):
        self.assertEqual(fill_profiles(self.profiles[:60], seed=45),
                         fill_profiles(self.profiles[:60], seed=45))

    def test_preserves_other_fields(self):
        originals = deepcopy(self.profiles[:80])
        new = fill_profiles(originals)
        self.assertEqual(originals, self.profiles[:80])
        for before, after in zip(originals, new):
            for key in before:
                if key not in {"compliance", "fns_data", "bank_account"}:
                    self.assertEqual(before[key], after[key])
            self.assertEqual(before["fns_data"].keys(), after["fns_data"].keys())
            for key in before["fns_data"]:
                if key != "has_account_block_115fz":
                    self.assertEqual(before["fns_data"][key], after["fns_data"][key])
            if not after["fns_data"]["has_account_block_115fz"]:
                self.assertEqual(before["bank_account"], after["bank_account"])

    def test_profile_contract_and_dataset_validator(self):
        result = fill_profiles(self.profiles, seed=45)
        for profile in result:
            validate_compliance_profile(profile)
            if profile["fns_data"]["has_account_block_115fz"]:
                self.assertEqual(profile["bank_account"]["status"], "blocked")
        self.assertTrue(validate_dataset(result, [], []).passed)

    def test_demo_has_adverse_cases(self):
        result = fill_profiles(self.profiles, scenario="demo", seed=45)
        self.assertTrue(any(p["compliance"]["sanctions_hit"] for p in result))
        self.assertTrue(any(p["fns_data"]["has_account_block_115fz"] for p in result))

    def test_sanctions_not_based_on_financials(self):
        p = deepcopy(self.profiles[0])
        good = deepcopy(p)
        good["financials"]["ebitda"] = 10**8
        good["financials"]["revenue_change_pct"] = 20
        bad = deepcopy(p)
        bad["financials"]["ebitda"] = -10**8
        bad["financials"]["revenue_change_pct"] = -50
        # Each call resets the RNG: sanctions are the first Bernoulli draw.
        a, _ = generate_compliance_data(good, rng=np.random.default_rng(900), scenario="demo")
        b, _ = generate_compliance_data(bad, rng=np.random.default_rng(900), scenario="demo")
        self.assertEqual(a["sanctions_hit"], b["sanctions_hit"])

    def test_prohibited_is_explicit_demo_policy_only(self):
        result = fill_profiles(self.profiles, scenario="demo", seed=45,
                               restricted_okved_prefixes=("62.01",))
        for p in result:
            self.assertEqual(p["compliance"]["is_prohibited_activity"],
                             p["company"]["okved_main"]["code"].startswith("62.01"))
        with self.assertRaisesRegex(ValueError, "demo"):
            fill_profiles(self.profiles[:2], scenario="baseline",
                          restricted_okved_prefixes=("62.01",))

    def test_inconsistent_bank_account_rejected(self):
        p = fill_profiles(self.profiles[:1], scenario="demo")[0]
        p["fns_data"]["has_account_block_115fz"] = True
        p["bank_account"]["status"] = "active"
        with self.assertRaisesRegex(ValueError, "blocked"):
            validate_compliance_profile(p)

    def test_invalid_source_rejected(self):
        p = fill_profiles(self.profiles[:1])[0]
        p["compliance"]["source"] = "unknown"
        with self.assertRaisesRegex(ValueError, "source"):
            validate_compliance_profile(p)

    def test_duplicate_borrower_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate borrower_id"):
            fill_profiles([self.profiles[0], deepcopy(self.profiles[0])])

    def test_does_not_modify_input(self):
        original = deepcopy(self.profiles[:10])
        fill_profiles(self.profiles[:10], scenario="demo")
        self.assertEqual(self.profiles[:10], original)

    def test_summary(self):
        profiles = fill_profiles(self.profiles[:200], seed=45, scenario="demo")
        stats = summarize(profiles, seed=45, scenario="demo")
        self.assertEqual(stats["count"], 200)
        for key in stats["shares"]:
            self.assertGreaterEqual(stats["shares"][key], 0)
            self.assertLessEqual(stats["shares"][key], 1)


if __name__ == "__main__":
    unittest.main()
