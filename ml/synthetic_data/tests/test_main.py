"""Small integration tests for in-memory end-to-end orchestration."""
import unittest
from datetime import date

from main import run_pipeline


class PipelineTests(unittest.TestCase):
    def test_pipeline_baseline_valid(self):
        result = run_pipeline(count=20, seed=42, as_of=date(2026, 9, 30))
        self.assertTrue(result["quality_report"]["passed"])
        self.assertEqual(len(result["profiles_compliance"]), 20)
        self.assertEqual(len(result["assessments_generated"]), 20)

    def test_pipeline_deterministic(self):
        opts = {"count": 8, "seed": 42, "scenario": "demo"}
        self.assertEqual(run_pipeline(**opts), run_pipeline(**opts))

    def test_stress_scenario_supported(self):
        r = run_pipeline(count=12, seed=50, scenario="stress_2025")
        self.assertTrue(r["quality_report"]["passed"])
        self.assertEqual(r["run_metadata"]["module_scenarios"]["bki"], "stress_2025")


if __name__ == "__main__":
    unittest.main()
