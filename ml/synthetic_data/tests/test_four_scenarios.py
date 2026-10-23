"""Regression tests for the PM's four fixed SME borrower scenarios."""
import json
import unittest
from copy import deepcopy
from pathlib import Path

from assessment import assess_applications
from four_scenarios import CASES, build_four_scenarios
from validation import validate_dataset

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "end_to_end"


class FourScenariosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build_four_scenarios()
        cls.profiles = cls.files["profiles.json"]
        cls.apps = cls.files["applications.json"]
        cls.assessments = cls.files["assessments.json"]

    def test_four_unique_borrowers_and_applications(self):
        self.assertEqual(len(self.profiles), 4)
        self.assertEqual(len(self.apps), 4)
        self.assertEqual(len({p["borrower_id"] for p in self.profiles}), 4)
        self.assertEqual(len({a["application_id"] for a in self.apps}), 4)
        self.assertEqual(len({s["assessment_id"] for s in self.assessments}), 4)

    def test_expected_routing_and_recommendations(self):
        by_name = dict(zip(CASES, self.assessments))
        self.assertEqual(by_name["ideal"]["route"], "green_zone")
        self.assertEqual(by_name["high_risk"]["route"], "auto_decline")
        self.assertEqual(by_name["borderline"]["route"], "analyst_escalation")
        self.assertEqual(by_name["new_business"]["route"], "analyst_escalation")
        self.assertEqual(by_name["borderline"]["ai_credit_memo"]["recommendation"], "counter_offer")
        trigger = next(x for x in by_name["borderline"]["counter_offer_triggers"]
                       if x["code"] == "amount_limit_exceeded")
        self.assertEqual(trigger["recommended_terms"]["amount"], 4_000_000)
        self.assertIn("bankruptcy", by_name["high_risk"]["auto_decline"]["reason_codes"])
        self.assertTrue(any(c["code"] == "business_age_lt_12m" and c["triggered"]
                            for c in by_name["new_business"]["escalation_checks"]))
        self.assertFalse(any(c["triggered"] for c in by_name["ideal"]["stop_factor_checks"]))

    def test_schema_and_referential_integrity(self):
        report = validate_dataset(self.profiles, self.files["applications_assessed.json"],
                                  self.assessments)
        self.assertTrue(report.passed, report.to_dict())
        for app, ass in zip(self.files["applications_assessed.json"], self.assessments):
            self.assertEqual(app["current_assessment_id"], ass["assessment_id"])
            self.assertEqual(app["application_id"], ass["application_id"])

    def test_stable_output_matches_committed_fixtures(self):
        for filename, generated in self.files.items():
            saved = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
            self.assertEqual(saved, generated, filename)

    def test_runs_without_random_seed_or_input_mutation(self):
        a, b = build_four_scenarios(), build_four_scenarios()
        self.assertEqual(a, b)
        profiles, apps = deepcopy(self.profiles), deepcopy(self.apps)
        assess_applications(profiles, apps)
        self.assertEqual(profiles, self.profiles)
        self.assertEqual(apps, self.apps)

    def test_new_business_shows_known_reporting_gap(self):
        p = self.profiles[CASES.index("new_business")]
        self.assertEqual(p["company"]["registration_date"], "2026-04-01")
        self.assertEqual(p["financials"]["cash_flow_last_12m"][:6], [0] * 6)
        self.assertEqual(p["financials"]["revenue_change_pct"], 0.0)
        # This 0% is a DEMO PLACEHOLDER, not a valid year-over-year growth rate;
        # schema needs nullable/missing-history semantics before production use.


if __name__ == "__main__":
    unittest.main()
