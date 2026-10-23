"""Unit tests for provisional synthetic credit rules and invariants."""
import unittest
from copy import deepcopy
from datetime import date

from company import generate_profiles
from applications import generate_applications
from assessment import (
    assess_applications, assess_one, first_year_debt_service, monthly_annuity,
)
from validation import validate_dataset


class AssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles, _ = generate_profiles(8, seed=42, as_of_date=date(2026, 9, 30))
        cls.apps, _ = generate_applications(cls.profiles, seed=46)

    def fixture(self):
        p, a = deepcopy(self.profiles[0]), deepcopy(self.apps[0])
        p["financials"].update({
            "annual_turnover": 20_000_000,
            "ebitda": 8_000_000,
            "revenue_change_pct": 6.0,
            "cash_flow_last_12m": [200_000] * 12,
        })
        p["bki_data"].update({
            "credit_history_quality": "good", "monthly_debt_service": 0,
            "active_loans_count": 0, "total_debt_amount": 0,
            "overdue_amount": 0, "max_overdue_days_12m": 0,
        })
        p["fns_data"].update({
            "bankruptcy_status": "none", "egrul_status": "active",
            "has_account_block_115fz": False, "is_mass_address": False,
            "is_mass_director": False, "has_tax_activity": True,
            "tax_arrears_amount": 0,
        })
        p["compliance"].update({"sanctions_hit": False, "is_prohibited_activity": False})
        a["loan_request"].update({"amount": 400_000, "term_months": 24, "repayment_type": "annuity"})
        a["collateral"] = {"type": "none", "description": None,
                           "market_value": None, "haircut_pct": None,
                           "valuation_source": None}
        a["pre_approval"]["max_amount"] = 4_000_000
        return p, a

    def test_ideal_green_zone(self):
        p, a = self.fixture()
        result, updated = assess_one(p, a)
        self.assertEqual(result["route"], "green_zone")
        self.assertEqual(updated["current_assessment_id"], result["assessment_id"])
        self.assertEqual(updated["status"], "underwriter_review")
        self.assertTrue(validate_dataset([p], [updated], [result]).passed)

    def test_bankruptcy_is_decline(self):
        p, a = self.fixture()
        p["fns_data"]["bankruptcy_status"] = "bankruptcy"
        result, updated = assess_one(p, a)
        self.assertEqual(result["route"], "auto_decline")
        self.assertIn("bankruptcy", result["auto_decline"]["reason_codes"])
        self.assertEqual(result["counter_offer_triggers"], [])
        self.assertEqual(updated["closure"]["reason"], "auto_declined")

    def test_above_limit_counter_and_analyst(self):
        p, a = self.fixture()
        a["loan_request"]["amount"] = 4_500_000
        result, _ = assess_one(p, a)
        self.assertEqual(result["route"], "analyst_escalation")
        counter = next(c for c in result["counter_offer_triggers"]
                       if c["code"] == "amount_limit_exceeded")
        self.assertEqual(counter["recommended_terms"]["amount"], 4_000_000)

    def test_young_business_escalates(self):
        p, a = self.fixture()
        # Only tests routing. Producing realistic <12m financial histories
        # requires an explicit missing-financials contract in a later stage.
        p["company"]["registration_date"] = "2026-04-01"
        result, _ = assess_one(p, a)
        self.assertEqual(result["route"], "analyst_escalation")
        self.assertIn("business_age_lt_12m", [c["code"] for c in
                     result["escalation_checks"] if c["triggered"]])

    def test_negative_ebitda_is_null_burden(self):
        p, a = self.fixture()
        p["financials"]["ebitda"] = -10_000
        result, updated = assess_one(p, a)
        self.assertIsNone(result["metrics"]["debt_burden_pct"])
        self.assertEqual(result["route"], "auto_decline")
        self.assertTrue(validate_dataset([p], [updated], [result]).passed)

    def test_1200_accounts_have_complete_contract_and_links(self):
        assessments, updated, _ = assess_applications(self.profiles, self.apps)
        self.assertEqual(len(assessments), len(self.apps))
        self.assertTrue(validate_dataset(self.profiles, updated, assessments).passed)
        self.assertEqual(len({a["assessment_id"] for a in assessments}), len(assessments))

    def test_deterministic_and_immutable(self):
        profiles, apps = deepcopy(self.profiles), deepcopy(self.apps)
        first = assess_applications(profiles, apps)
        self.assertEqual(first, assess_applications(profiles, apps))
        self.assertEqual(profiles, self.profiles)
        self.assertEqual(apps, self.apps)

    def test_annuity_short_term_only_six_payments(self):
        self.assertAlmostEqual(monthly_annuity(1_000_000, 12, 0), 1_000_000 / 12)
        self.assertEqual(first_year_debt_service(120_000, 6, 0, "annuity"), 120_000)
        self.assertEqual(first_year_debt_service(120_000, 6, 0, "differentiated"), 120_000)

    def test_ltv_uses_haircut(self):
        p, a = self.fixture()
        a["collateral"].update({"type": "real_estate", "market_value": 1_000_000,
                                 "valuation_source": "client"})
        a["loan_request"]["amount"] = 900_000
        result, _ = assess_one(p, a)
        self.assertAlmostEqual(result["metrics"]["ltv_pct"], 128.57, places=2)
        self.assertTrue(any(c["code"] == "ltv_exceeded" for c in result["counter_offer_triggers"]))

    def test_invalid_confidence(self):
        p, a = self.fixture()
        with self.assertRaises(ValueError):
            assess_one(p, a, mock_confidence_pct=150)

    def test_wrong_borrower(self):
        p, a = self.fixture()
        a["borrower_id"] = "brw_unknown"
        with self.assertRaises(ValueError):
            assess_one(p, a)


if __name__ == "__main__":
    unittest.main()
