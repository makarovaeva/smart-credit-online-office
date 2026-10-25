import json
import unittest
from pathlib import Path
from unittest.mock import patch
from io import BytesIO

from ml.document_agent.providers import OpenAICompatibleProvider, StaticDemoProvider
from ml.document_agent.schema import UploadedDocument, DocumentAnalysis
from ml.document_agent.service import inspect_package

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_input.json"


def load_demo():
    return json.loads(DEMO.read_text(encoding="utf-8"))


class ServiceTests(unittest.TestCase):
    def run_demo(self, batch):
        return inspect_package(batch, StaticDemoProvider(batch.get("mock_responses", {})))

    def test_missing_financial_statements(self):
        result = self.run_demo(load_demo())
        self.assertEqual(result["status"], "needs_documents")
        self.assertEqual(result["missing_document_types"], ["financial_statements"])
        self.assertIn("отчётность", result["customer_message"])

    def test_complete_provisional(self):
        batch = load_demo()
        batch["documents"].append({"document_id": "doc_fin", "filename": "fin.txt", "text": "Бухгалтерский баланс. Выручка 5000000."})
        batch["mock_responses"]["doc_fin"] = {"document_type": "financial_statements", "borrower_id": None,
            "evidence": ["Бухгалтерский баланс"], "requires_review": False}
        self.assertEqual(self.run_demo(batch)["status"], "package_complete_provisional")

    def test_ip_does_not_require_financial_statements_in_demo_rule(self):
        batch = load_demo()
        batch["borrower"]["company"]["legal_form"] = "ip"
        self.assertEqual(self.run_demo(batch)["missing_document_types"], [])

    def test_collateral_requires_ownership_proof(self):
        batch = load_demo()
        batch["application"]["collateral"] = {"type": "real_estate"}
        self.assertEqual(self.run_demo(batch)["missing_document_types"], ["financial_statements", "collateral_proof"])

    def test_failed_provider_is_review_not_success(self):
        batch = load_demo()
        batch["mock_responses"]["doc_bank"] = {"document_type": "not_real"}
        result = self.run_demo(batch)
        self.assertIn("bank_statement", result["missing_document_types"])
        self.assertTrue(result["requires_human_review"])

    def test_unsubstantiated_evidence_is_rejected(self):
        batch = load_demo()
        batch["mock_responses"]["doc_reg"]["evidence"] = ["не существующий фрагмент"]
        result = self.run_demo(batch)
        self.assertIn("registration_extract", result["missing_document_types"])
        self.assertIn("unsupported_classification_evidence", result["documents"][0]["issues"])

    def test_borrower_mismatch(self):
        batch = load_demo()
        batch["documents"][0]["text"] += " borrower_OTHER_2"
        batch["mock_responses"]["doc_reg"]["borrower_id"] = "borrower_OTHER_2"
        result = self.run_demo(batch)
        self.assertIn("registration_extract", result["missing_document_types"])
        self.assertTrue(result["requires_human_review"])

    def test_invalid_input_ids_fail(self):
        batch = load_demo()
        batch["borrower"]["borrower_id"] = "wrong"
        with self.assertRaises(ValueError):
            self.run_demo(batch)

    def test_no_text_requires_review(self):
        batch = load_demo()
        batch["documents"][1]["text"] = ""
        result = self.run_demo(batch)
        self.assertIn("bank_statement", result["missing_document_types"])
        self.assertTrue(result["requires_human_review"])

    def test_unknown_response_schema_rejected(self):
        with self.assertRaises(ValueError):
            DocumentAnalysis.from_json({"document_type": "scoring_decision"})

    def test_trusted_https_for_remote(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider(base_url="http://example.com/v1", model="x")
        instance = OpenAICompatibleProvider(base_url="http://127.0.0.1:11434/v1", model="qwen:latest")
        self.assertEqual(instance.url, "http://127.0.0.1:11434/v1/chat/completions")

    def test_zai_api_base_url(self):
        provider = OpenAICompatibleProvider(
            base_url="https://api.z.ai/api/paas/v4/", model="glm-4.7-flash", api_key="test"
        )
        self.assertEqual(provider.url, "https://api.z.ai/api/paas/v4/chat/completions")

    def test_rejects_endpoint_instead_of_base(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider(
                base_url="https://api.z.ai/api/paas/v4/chat/completions", model="glm-4.7-flash"
            )

    def test_zai_adapter_request_and_validation(self):
        provider = OpenAICompatibleProvider(
            base_url="https://api.z.ai/api/paas/v4", model="glm-4.7-flash", api_key="fake-test-key"
        )
        reply = {"choices": [{"message": {"content": json.dumps({
            "document_type": "registration_extract", "borrower_id": None,
            "evidence": ["Сведения из ЕГРЮЛ"], "requires_review": False,
        }, ensure_ascii=False)}}]}

        class MockHTTP:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return json.dumps(reply, ensure_ascii=False).encode("utf-8")

        with patch("ml.document_agent.providers.urlopen", return_value=MockHTTP()) as called:
            analysis = provider.analyze(UploadedDocument("id", "extract.txt", "Сведения из ЕГРЮЛ"))
        request = called.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.z.ai/api/paas/v4/chat/completions")
        self.assertEqual(body["model"], "glm-4.7-flash")
        self.assertIn("Сведения из ЕГРЮЛ", body["messages"][1]["content"])
        self.assertEqual(analysis.document_type, "registration_extract")

    def test_external_provider_response(self):
        provider = OpenAICompatibleProvider(base_url="https://api.example.com/v1", model="test", api_key="demo")
        sample = {"choices": [{"message": {"content": json.dumps({
            "document_type": "bank_statement", "borrower_id": None,
            "evidence": ["Выписка"], "requires_review": False,
        })}}]}

        class MockHTTP:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return json.dumps(sample).encode("utf-8")

        with patch("ml.document_agent.providers.urlopen", return_value=MockHTTP()) as mock_open:
            result = provider.analyze(UploadedDocument("id", "file.txt", "Выписка"))
        self.assertEqual(result.document_type, "bank_statement")
        self.assertEqual(mock_open.call_args.kwargs["timeout"], 40)


if __name__ == "__main__":
    unittest.main()
