"""Feature contract JSON must match the feature allowlist used by the trainer."""
import json
import unittest
from pathlib import Path
from train_scoring import CATEGORICAL, NUMERICAL, FEATURES, LABEL

CONTRACT_FILE = Path(__file__).resolve().parents[1] / "feature_contract.json"

class FeatureContractTests(unittest.TestCase):
    def test_contract_matches_implemented_features(self):
        contract = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
        self.assertEqual(contract["categorical_features"], list(CATEGORICAL))
        self.assertEqual(contract["numerical_features"], list(NUMERICAL))
        self.assertEqual(contract["features_order"], list(FEATURES))
        self.assertEqual([x["name"] for x in contract["features"]], list(FEATURES))
        self.assertEqual(len(FEATURES), 28)

    def test_target_and_identifiers_not_features(self):
        contract = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
        self.assertEqual(contract["target"]["name"], LABEL)
        self.assertTrue(contract["target"]["is_feature"] is False)
        self.assertFalse(set(contract["identifiers"]) & set(FEATURES))
        self.assertFalse({LABEL, "simulator_probability"} & set(FEATURES))
        self.assertTrue(all(not x["nullable"] for x in contract["features"]))

if __name__ == "__main__":
    unittest.main()
