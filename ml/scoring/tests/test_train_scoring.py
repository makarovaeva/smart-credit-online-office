"""Run separately from core tests because pandas/scikit-learn are optional ML deps."""
import copy
import importlib.util
import sys
import tempfile
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

# The synthetic-data generator is a sibling module, not part of scoring.
SYNTHETIC_ROOT = Path(__file__).resolve().parents[2] / "synthetic_data"
sys.path.insert(0, str(SYNTHETIC_ROOT))
# Load synthetic_data/main.py explicitly: scoring/main.py has the same basename.
spec_synth = importlib.util.spec_from_file_location("synthetic_generator_entry_for_training_tests", SYNTHETIC_ROOT / "main.py")
synthetic_entry = importlib.util.module_from_spec(spec_synth)
spec_synth.loader.exec_module(synthetic_entry)
run_pipeline = synthetic_entry.run_pipeline
from train_scoring import (
    FEATURES, LABEL, _metrics, extract_features, load_observed_labels,
    make_splits, simulate_demo_labels, train, compare_models,
)


class ScoringTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = run_pipeline(count=240, seed=47)
        cls.profiles = data["profiles_compliance"]
        cls.apps = data["applications_generated"]
        cls.assessed = data["applications_assessed"]
        cls.features = extract_features(cls.profiles, cls.apps)
        cls.labels = simulate_demo_labels(cls.features, seed=24)

    def test_features_match_contract_and_exclude_decisions(self):
        self.assertEqual(len(self.features), 240)
        self.assertTrue(set(FEATURES).issubset(self.features.columns))
        for leaked in ("route", "risk_grade", "risk_score", "model_confidence_pct", "assessment_id", LABEL):
            self.assertNotIn(leaked, self.features.columns)

    def test_assessed_application_rejected(self):
        with self.assertRaisesRegex(ValueError, "applications_generated"):
            extract_features(self.profiles, self.assessed)

    def test_invariant_to_profile_application_order(self):
        reversed_features = extract_features(list(reversed(self.profiles)), list(reversed(self.apps)))
        left = self.features.sort_values("application_id").reset_index(drop=True)
        right = reversed_features.sort_values("application_id").reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right)

    def test_simulated_labels_reproducible_and_order_independent(self):
        labels1 = self.labels.sort_values("application_id").reset_index(drop=True)
        labels2 = simulate_demo_labels(self.features.sample(frac=1, random_state=123), seed=24)
        labels2 = labels2.sort_values("application_id").reset_index(drop=True)
        pd.testing.assert_frame_equal(labels1, labels2)
        labels3 = simulate_demo_labels(self.features, seed=25)
        self.assertTrue((self.labels[LABEL] != labels3[LABEL]).any())
        self.assertTrue(((labels1["simulator_probability"] >= 0) & (labels1["simulator_probability"] <= 1)).all())

    def test_bad_foreign_key_and_duplicate_application_rejected(self):
        apps = copy.deepcopy(self.apps)
        apps[0]["borrower_id"] = "brw_not_found"
        with self.assertRaisesRegex(ValueError, "Unknown borrower"):
            extract_features(self.profiles, apps)
        with self.assertRaisesRegex(ValueError, "Duplicate application_id"):
            extract_features(self.profiles, self.apps + [self.apps[0]])

    def test_observed_labels_require_complete_unique_binary_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "labels.csv"
            self.labels[["application_id", LABEL]].to_csv(p, index=False)
            valid = load_observed_labels(p, self.features["application_id"].tolist())
            self.assertEqual(len(valid), 240)
            valid.iloc[:-1].to_csv(p, index=False)
            with self.assertRaisesRegex(ValueError, "match"):
                load_observed_labels(p, self.features["application_id"].tolist())
            doubled = pd.concat([valid, valid.iloc[[0]]], ignore_index=True)
            doubled.to_csv(p, index=False)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_observed_labels(p, self.features["application_id"].tolist())

    def test_gini_and_auc_identity(self):
        metrics = _metrics(np.array([0, 0, 1, 1]), np.array([0.1, 0.4, 0.35, 0.8]), 42, False)
        self.assertEqual(metrics["roc_auc"], 0.75)
        self.assertEqual(metrics["gini"], 0.5)

    def test_group_splits_do_not_leak_borrower(self):
        data = self.features.merge(self.labels[["application_id", LABEL]], on="application_id")
        chunks = make_splits(data, data[LABEL].to_numpy(), seed=31)
        for name, idx in chunks.items():
            self.assertEqual(len(set(data.iloc[idx][LABEL])), 2, name)
        a, b, c = [set(data.iloc[idx].borrower_id) for idx in chunks.values()]
        self.assertFalse(a & b or a & c or b & c)
        self.assertEqual(sum(len(x) for x in chunks.values()), len(data))
        data2 = pd.concat([data, data.iloc[:50].assign(application_id=lambda x: x.application_id + "_repeat")], ignore_index=True)
        grouped = make_splits(data2, data2[LABEL].to_numpy(), seed=31)
        groups = [set(data2.iloc[idx].borrower_id) for idx in grouped.values()]
        self.assertFalse(groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])

    def test_few_event_samples_rejected(self):
        data = self.features.copy()
        data[LABEL] = 0
        data.loc[:3, LABEL] = 1
        with self.assertRaisesRegex(ValueError, ">=10"):
            train(data)

    def test_logistic_regression_baseline(self):
        data = self.features.merge(self.labels[["application_id", LABEL]], on="application_id")
        model, report, predictions = train(data, seed=31, model_name="logistic")
        self.assertEqual(report["model"], "logistic")
        self.assertEqual(len(report["feature_importance"]), len(FEATURES))
        self.assertTrue(0 <= report["splits"]["test"]["roc_auc"] <= 1)
        self.assertTrue(predictions.predicted_risk_score_demo.between(0, 1).all())
        self.assertTrue(hasattr(model, "predict_proba"))

    def test_all_models_use_same_heldout_applications_and_targets(self):
        data = self.features.merge(self.labels[["application_id", LABEL]], on="application_id")
        models, comparison, meta = compare_models(data, seed=31)
        self.assertEqual(set(models), {"logistic", "catboost", "lightgbm"})
        self.assertEqual(set(comparison["model"]), set(models))
        self.assertEqual(set(comparison["split"]), {"train", "val", "test"})
        self.assertTrue(meta["same_splits_for_all_models"])
        ids = [set(predictions.application_id) for _, _, predictions in models.values()]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ids[0], ids[2])
        for name in models:
            actual = models[name][1]["splits"]["test"]
            expected = comparison.query("model == @name and split == 'test'").iloc[0]
            self.assertEqual(actual["roc_auc"], expected["roc_auc"])
            self.assertAlmostEqual(actual["gini"], 2 * actual["roc_auc"] - 1, places=4)

    def test_catboost_smoke_and_metrics(self):
        data = self.features.merge(self.labels[["application_id", LABEL]], on="application_id")
        model, report, predictions = train(data, seed=31, model_name="catboost")
        self.assertIn("roc_auc", report["splits"]["test"])
        self.assertAlmostEqual(report["splits"]["test"]["gini"],
                               2 * report["splits"]["test"]["roc_auc"] - 1, places=4)
        self.assertTrue(predictions.predicted_risk_score_demo.between(0, 1).all())
        self.assertEqual(len(report["features"]), len(FEATURES))
        self.assertTrue(hasattr(model, "save_model"))

    @unittest.skipUnless(importlib.util.find_spec("lightgbm"), "LightGBM not installed")
    def test_lightgbm_smoke(self):
        data = self.features.merge(self.labels[["application_id", LABEL]], on="application_id")
        model, report, predictions = train(data, seed=31, model_name="lightgbm")
        self.assertGreaterEqual(report["splits"]["test"]["roc_auc"], 0.0)
        self.assertLessEqual(report["splits"]["test"]["roc_auc"], 1.0)
        self.assertEqual(report["model"], "lightgbm")
        self.assertTrue(predictions.predicted_risk_score_demo.between(0, 1).all())


if __name__ == "__main__":
    unittest.main()
