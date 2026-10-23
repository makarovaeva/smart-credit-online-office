"""Tests for synthetic credit applications and integration with validation.py."""
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

import numpy as np

from company import generate_profiles
from applications import (
    generate_applications, preliminary_limit, validate_application,
)
from validation import validate_dataset


class ApplicationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles, _ = generate_profiles(200, seed=42, as_of_date=date(2026, 9, 30))

    def test_deterministic_seed(self):
        a, _ = generate_applications(self.profiles, seed=46)
        b, _ = generate_applications(self.profiles, seed=46)
        self.assertEqual(a, b)

    def test_input_immutable(self):
        original = deepcopy(self.profiles)
        generate_applications(self.profiles)
        self.assertEqual(original, self.profiles)

    def test_all_fields_and_contract(self):
        applications, metadata = generate_applications(self.profiles)
        self.assertEqual(len(applications), len(self.profiles))
        self.assertEqual(metadata["applications"], len(applications))
        by_borrower = {p["borrower_id"]: p for p in self.profiles}
        for app in applications:
            validate_application(app, by_borrower[app["borrower_id"]])
            self.assertEqual(set(app), {
                "application_id", "application_number", "borrower_id", "status",
                "status_changed_at", "routing_status", "current_assessment_id",
                "loan_request", "purpose", "collateral", "pre_approval", "consents",
                "document_requirements", "assignment", "closure", "created_at", "updated_at",
            })
        self.assertEqual(len(set(a["application_id"] for a in applications)), len(applications))
        self.assertEqual(len(set(a["borrower_id"] for a in applications)), len(applications))
        self.assertTrue(validate_dataset(self.profiles, applications).passed)

    def test_application_rate_zero(self):
        self.assertEqual(generate_applications(self.profiles, application_rate=0)[0], [])

    def test_subset_application_rate(self):
        apps, _ = generate_applications(self.profiles, application_rate=0.37)
        self.assertGreater(len(apps), 0)
        self.assertLess(len(apps), len(self.profiles))
        self.assertEqual(len(set(a["borrower_id"] for a in apps)), len(apps))

    def test_demo_has_above_limit_cases(self):
        apps, summary = generate_applications(self.profiles, scenario="demo")
        self.assertGreater(summary["by_limit"].get("above_limit", 0), 0)
        self.assertTrue(any(a["loan_request"]["amount"] > a["pre_approval"]["max_amount"]
                            for a in apps))

    def test_collateral_null_and_nonnull(self):
        apps, _ = generate_applications(self.profiles, scenario="demo")
        self.assertTrue(any(a["collateral"]["type"] == "none" for a in apps))
        self.assertTrue(any(a["collateral"]["market_value"] is not None for a in apps))
        for a in apps:
            if a["collateral"]["type"] in {"none", "guarantee"}:
                self.assertIsNone(a["collateral"]["market_value"])

    def test_duplicate_borrower_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate borrower"):
            generate_applications([self.profiles[0], deepcopy(self.profiles[0])])

    def test_invalid_turnover_rejected(self):
        p = deepcopy(self.profiles[0])
        p["financials"]["annual_turnover"] = -1
        with self.assertRaisesRegex(ValueError, "annual_turnover"):
            generate_applications([p])

    def test_invalid_application_rate_rejected(self):
        for value in (-0.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                generate_applications(self.profiles, application_rate=value)

    def test_no_policy_route_at_submission(self):
        apps, _ = generate_applications(self.profiles)
        for a in apps:
            self.assertIsNone(a["current_assessment_id"])
            self.assertEqual(a["routing_status"], "not_routed")
            self.assertEqual(a["status"], "application_submitted")

    def test_null_preapproval_for_zero_turnover_is_zero(self):
        p = deepcopy(self.profiles[0])
        p["financials"]["annual_turnover"] = 0
        apps, _ = generate_applications([p])
        self.assertEqual(apps[0]["pre_approval"]["max_amount"], 0)
        self.assertGreater(apps[0]["loan_request"]["amount"], 0)


if __name__ == "__main__":
    unittest.main()
