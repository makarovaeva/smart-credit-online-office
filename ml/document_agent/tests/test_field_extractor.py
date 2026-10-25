"""No network required. Synthetic fixtures; no loan decisions."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ml.document_agent.field_extractor import (
    extract_verified_fields, evaluate_cases, _amount_in_quote
)
from ml.document_agent.providers import OpenAICompatibleProvider, StaticDemoProvider
from ml.document_agent.schema import DocumentFieldAnalysis, UploadedDocument
from ml.document_agent.main import run_review

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples" / "realistic" / "cases.json"


class TestFinancialExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]

    def get_case(self, id):
        case = next(c for c in self.cases if c["id"] == id)
        document = UploadedDocument(id, case["filename"], (CASES.parent / case["filename"]).read_text(encoding="utf-8"))
        return case, document

    def test_seven_realistic_cases_exact_match(self):
        output = evaluate_cases(CASES, provider_name="mock")
        self.assertEqual(output["cases"], 7)
        self.assertEqual(output["field_exact_matches"], output["field_evaluations"])
        self.assertEqual(output["document_type_correct"], 7)
        self.assertTrue(all(r["expected_issues_found"] for r in output["records"]))

    def test_amount_units_rubles_thousands_millions(self):
        self.assertTrue(_amount_in_quote(18_460_000, "2110 Выручка (тыс. руб.) 18 460"))
        self.assertTrue(_amount_in_quote(18_120_250, "Всего поступило 18 120 250,00 руб."))
        self.assertTrue(_amount_in_quote(3_000_000, "Сумма 3 млн руб."))
        self.assertFalse(_amount_in_quote(18_460_000, "Выручка 18 460 руб."))
        self.assertFalse(_amount_in_quote(2_740_000, "Чистая прибыль 2 740 руб."))

    def test_invalid_amount_no_evidence_is_never_accepted(self):
        c, doc = self.get_case("fin25")
        response = json.loads(json.dumps(c["mock_response"]))
        response["fields"]["annual_revenue_rub"]["value"] = 999_000_000
        result = extract_verified_fields(doc, StaticDemoProvider({doc.document_id: response}), expected_inn=c["expected_inn"])
        self.assertIsNone(result["fields"]["annual_revenue_rub"]["value"])
        self.assertIn("annual_revenue_rub:amount_not_supported_by_evidence_or_units", result["issues"])
        self.assertTrue(result["requires_review"])

    def test_fake_quote_is_not_accepted(self):
        c, doc = self.get_case("bank25")
        response = json.loads(json.dumps(c["mock_response"]))
        response["fields"]["bank_inflows_rub"]["evidence"] = "100% оплата кредита одобрена"
        result = extract_verified_fields(doc, StaticDemoProvider({doc.document_id: response}))
        self.assertIsNone(result["fields"]["bank_inflows_rub"]["value"])
        self.assertIn("bank_inflows_rub:evidence_not_in_document", result["issues"])

    def test_period_from_unsupported_in_quote(self):
        c, doc = self.get_case("fin24")
        response = json.loads(json.dumps(c["mock_response"]))
        response["fields"]["period_from"]["value"] = "2023-01-01"
        result = extract_verified_fields(doc, StaticDemoProvider({doc.document_id: response}))
        self.assertIsNone(result["fields"]["period_from"]["value"])
        self.assertIn("period_from:date_not_supported_by_evidence", result["issues"])

    def test_wrong_inn_is_review_not_credit_rejection(self):
        c, doc = self.get_case("bank_wrong")
        result = extract_verified_fields(doc, StaticDemoProvider({doc.document_id: c["mock_response"]}), expected_inn="7701234567")
        self.assertIn("company_inn_mismatch", result["issues"])
        self.assertNotIn("decision", result)

    def test_prompt_injection_is_flagged(self):
        c, doc = self.get_case("fin_injection")
        result = extract_verified_fields(doc, StaticDemoProvider({doc.document_id: c["mock_response"]}))
        self.assertIn("possible_prompt_injection", result["issues"])
        self.assertIsNone(result["fields"]["ebitda_rub"]["value"])
        self.assertTrue(result["requires_review"])

    def test_schema_rejects_unknown_fields_and_non_integer_amount(self):
        c, _ = self.get_case("fin25")
        obj = json.loads(json.dumps(c["mock_response"]))
        obj["fields"]["decision"] = {"value": "approve", "evidence": "approve"}
        with self.assertRaises(ValueError):
            DocumentFieldAnalysis.from_json(obj)
        obj = json.loads(json.dumps(c["mock_response"]))
        obj["fields"]["annual_revenue_rub"]["value"] = 18460000.0
        with self.assertRaises(ValueError):
            DocumentFieldAnalysis.from_json(obj)

    def test_api_transport_sends_field_prompt_without_api_key_in_json(self):
        c, doc = self.get_case("bank25")
        provider = OpenAICompatibleProvider(base_url="https://api.z.ai/api/paas/v4", model="glm-4.7-flash", api_key="dummy-secret")
        reply = {"choices": [{"message": {"content": json.dumps(c["mock_response"], ensure_ascii=False)}}]}

        class MockHTTP:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, n): return json.dumps(reply).encode("utf-8")

        with patch("ml.document_agent.providers.urlopen", return_value=MockHTTP()) as caller:
            extracted = extract_verified_fields(doc, provider, expected_inn="7701234567")
        req = caller.call_args.args[0]
        body = json.loads(req.data.decode("utf-8"))
        self.assertIn("annual_revenue_rub", body["messages"][0]["content"])
        self.assertIn("bank_inflows_rub", body["messages"][0]["content"])
        self.assertEqual(body["response_format"]["type"], "json_object")
        self.assertNotIn("dummy-secret", req.data.decode("utf-8"))
        self.assertEqual(extracted["fields"]["bank_inflows_rub"]["value"], 18_120_250)

    def test_integrated_mode_does_not_change_document_status(self):
        raw = json.loads((ROOT / "examples" / "backend_complete_input.json").read_text(encoding="utf-8"))
        # Use existing classification fixtures; fields are extracted separately.
        raw["mock_field_responses"] = {}
        for id, example_case in (("doc-bank-1", "bank25"), ("doc-fin-1", "fin25")):
            raw["mock_field_responses"][id] = next(c for c in self.cases if c["id"] == example_case)["mock_response"]
            raw["mock_text_by_id"][id] = (CASES.parent / next(c for c in self.cases if c["id"] == example_case)["filename"]).read_text(encoding="utf-8")
        # Update classifying response evidence to the longer file text.
        raw["mock_responses"]["doc-bank-1"]["evidence"] = ["Выписка по расчетному счету"]
        raw["mock_responses"]["doc-fin-1"]["evidence"] = ["Бухгалтерская (финансовая) отчетность"]
        provider = StaticDemoProvider(raw["mock_responses"], field_responses=raw["mock_field_responses"])
        old = run_review(raw, provider=provider, parser_mode="mock")
        new = run_review(raw, provider=provider, parser_mode="mock", extract_fields=True)
        self.assertEqual(new["status"], old["status"])
        self.assertEqual(new["missing_document_types"], old["missing_document_types"])
        self.assertEqual(len(new["field_extractions"]), 2)
        self.assertEqual(new["field_extractions"][1]["fields"]["annual_revenue_rub"]["value"], 18460000)

if __name__ == "__main__":
    unittest.main()
