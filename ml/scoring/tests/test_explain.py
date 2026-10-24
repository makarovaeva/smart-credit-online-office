"""Explainability checks: model attribution != underwriting reason."""
import unittest
import numpy as np
import pandas as pd

from explain import (
    FEATURES, FEATURE_LABELS, _base_value, _binary_shap_values,
    summarize_factors, policy_explanation, compute_shap,
)


class ExplainTests(unittest.TestCase):
    def test_all_source_features_have_plain_language_labels(self):
        self.assertEqual(set(FEATURE_LABELS), set(FEATURES))

    def test_binary_shap_shape(self):
        matrix = np.ones((2, len(FEATURES)))
        out = _binary_shap_values([matrix * -1, matrix], 2, len(FEATURES))
        np.testing.assert_array_equal(out, matrix)
        with self.assertRaisesRegex(ValueError, "shape"):
            _binary_shap_values(np.zeros((2, 3)), 2, len(FEATURES))

    def test_base_value_validation(self):
        self.assertEqual(_base_value(np.array([0.2])), 0.2)
        self.assertEqual(_base_value(np.array([-0.2, 0.4])), 0.4)
        with self.assertRaisesRegex(ValueError, "expected_value"):
            _base_value([1.0, 2.0, 3.0])

    def test_risk_direction_is_about_model_not_bank_decision(self):
        phi = np.zeros(len(FEATURES))
        phi[FEATURES.index("credit_history_quality")] = 1.2
        phi[FEATURES.index("ebitda_margin_pct")] = -0.5
        higher, lower = summarize_factors(phi, top_n=2)
        self.assertEqual([x["feature"] for x in higher], ["credit_history_quality"])
        self.assertEqual([x["feature"] for x in lower], ["ebitda_margin_pct"])
        self.assertIn("модельную оценку риска", higher[0]["customer_text"])
        self.assertNotIn("отказ", higher[0]["customer_text"].lower())

    def test_top_n_bounds(self):
        with self.assertRaises(ValueError):
            summarize_factors(np.zeros(len(FEATURES)), top_n=0)

    def test_policy_reason_codes_do_not_come_from_shap(self):
        assessment = {
            "assessment_id": "test_id", "route": "auto_decline",
            "stop_factor_checks": [
                {"code": "bankruptcy", "triggered": True},
                {"code": "dscr_below_0_9", "triggered": True},
                {"code": "sanctions", "triggered": False},
            ],
            "escalation_checks": [{"code": "business_age_lt_12m", "triggered": False}],
            "green_zone_checks": [{"code": "dscr", "passed": False}],
        }
        result = policy_explanation(assessment)
        self.assertEqual(result["route"], "auto_decline")
        self.assertEqual(result["reason_codes"], ["bankruptcy", "dscr_below_0_9"])
        self.assertIn("НЕ SHAP", result["note"])

    def test_green_zone_not_declared_final_approval(self):
        r = policy_explanation({"route": "green_zone"})
        self.assertIn("окончательное решение ещё не принято", r["customer_message"])

    def test_invalid_policy_route(self):
        with self.assertRaises(ValueError):
            policy_explanation({"route": "final_approval"})

    def test_linear_shap_aggregates_onehot_to_original_28(self):
        # Small self-contained model with *the same* training preprocessing.
        from sklearn.compose import ColumnTransformer
        from sklearn.preprocessing import StandardScaler, OneHotEncoder
        from sklearn.pipeline import Pipeline
        from sklearn.linear_model import LogisticRegression
        from train_scoring import CATEGORICAL, NUMERICAL
        n = 60
        frame = pd.DataFrame({c: np.linspace(0.2, 10.0, n) + i for i,c in enumerate(NUMERICAL)})
        for j,c in enumerate(CATEGORICAL):
            frame[c] = ['a' if (i+j) % 3 else 'b' for i in range(n)]
        frame = frame[FEATURES]
        pre = ColumnTransformer([
            ('numeric', StandardScaler(), list(NUMERICAL)),
            ('categorical', OneHotEncoder(handle_unknown='ignore', sparse_output=False), list(CATEGORICAL)),
        ])
        pipeline = Pipeline([('preprocess', pre), ('classifier', LogisticRegression(max_iter=1000))])
        y = np.array([int(i % 4 == 0) for i in range(n)])
        pipeline.fit(frame, y)
        baseline, effects, raw = compute_shap(pipeline, 'logistic', frame.iloc[:3], frame.iloc[3:33])
        self.assertEqual(effects.shape, (3, 28))
        np.testing.assert_allclose(baseline + effects.sum(axis=1), raw, atol=1e-6)


if __name__ == '__main__':
    unittest.main()
