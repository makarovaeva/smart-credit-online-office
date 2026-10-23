"""Tests for generation, contract compatibility and reproducibility."""
import unittest
from datetime import date

from company import generate_profiles, make_inn, make_ogrn
from validation import validate_dataset
import numpy as np


class CompanyGeneratorTests(unittest.TestCase):
    def test_reproducible_and_changes_with_seed(self):
        a, metadata = generate_profiles(20, seed=42)
        b, _ = generate_profiles(20, seed=42)
        c, _ = generate_profiles(20, seed=43)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(metadata["count"], 20)

    def test_contract_fields_and_semantics(self):
        profiles, _ = generate_profiles(200, seed=5)
        report = validate_dataset(profiles, [])
        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual(len({p["borrower_id"] for p in profiles}), len(profiles))
        self.assertEqual(len({p["company"]["inn"] for p in profiles}), len(profiles))
        for profile in profiles:
            company = profile["company"]
            self.assertIn(company["legal_form"], ("ooo", "ip"))
            self.assertEqual(len(profile["financials"]["cash_flow_last_12m"]), 12)
            self.assertLessEqual(profile["financials"]["annual_turnover"],
                                 120_000_000 if company["employees_count"] <= 15 else 800_000_000)
            self.assertEqual(sum(o["ownership_share_pct"] for o in profile["owners"]), 100.0)
            self.assertEqual(len(profile["borrower_id"].removeprefix("brw_")), 26)
            if company["legal_form"] == "ip":
                self.assertIsNone(company["kpp"])
                self.assertEqual(company["inn"], profile["head"]["inn_individual"])

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            generate_profiles(0)
        with self.assertRaises(ValueError):
            generate_profiles(1, mix="unknown")
        with self.assertRaises(ValueError):
            generate_profiles(1, as_of_date=date(2001, 1, 1))

    def test_identifier_check_digits(self):
        rng = np.random.default_rng(1)
        for _ in range(20):
            oo = make_inn("ooo", rng, "77")
            ip = make_inn("ip", rng, "78")
            ogrn = make_ogrn("ooo", rng, "77", 2021)
            ogrnip = make_ogrn("ip", rng, "78", 2021)
            self.assertEqual(len(oo), 10)
            self.assertEqual(len(ip), 12)
            self.assertEqual(len(ogrn), 13)
            self.assertEqual(len(ogrnip), 15)
            self.assertEqual(int(oo[-1]), sum(a*b for a, b in zip(map(int, oo[:-1]),
                                        (2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10)
            self.assertEqual(int(ip[-2]), sum(a*b for a, b in zip(map(int, ip[:10]),
                                        (7, 2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10)
            self.assertEqual(int(ip[-1]), sum(a*b for a, b in zip(map(int, ip[:11]),
                                        (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10)
            self.assertEqual(int(ogrn[-1]), int(ogrn[:-1]) % 11 % 10)
            self.assertEqual(int(ogrnip[-1]), int(ogrnip[:-1]) % 13 % 10)


if __name__ == "__main__":
    unittest.main()
