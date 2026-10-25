"""Whitespace-tolerant citations without semantic/amount relaxation."""
import json
from pathlib import Path
import unittest

from ml.document_agent.field_extractor import _evidence_in_document, extract_verified_fields
from ml.document_agent.providers import StaticDemoProvider
from ml.document_agent.schema import UploadedDocument

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples" / "realistic" / "cases.json"


class TestEvidenceSpacing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = next(c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]
                        if c["id"] == "fin25")
        cls.text = (CASES.parent / cls.case["filename"]).read_text(encoding="utf-8")

    def extract_with_quote(self, quote, value=18_460_000):
        c = self.case
        answer = json.loads(json.dumps(c["mock_response"]))
        answer["fields"]["annual_revenue_rub"] = {"value": value, "evidence": quote}
        document = UploadedDocument("fin25", c["filename"], self.text)
        return extract_verified_fields(document, StaticDemoProvider({"fin25": answer}))

    def test_tabular_spaces_pipes_and_narrow_no_break_space(self):
        # Source line contains alignment spaces and pipes, as in our GLM fixture.
        quote = "2110 | Выручка (тыс. руб.)\u00a0| 18\u202f460 | 15 100"
        self.assertTrue(_evidence_in_document(quote, self.text))
        result = self.extract_with_quote(quote)
        self.assertEqual(result["fields"]["annual_revenue_rub"]["value"], 18_460_000)
        self.assertNotIn("annual_revenue_rub:evidence_not_in_document", result["issues"])

    def test_missing_pipes_with_collapsed_spaces(self):
        quote = "2110 Выручка (тыс. руб.) 18 460 15 100"
        self.assertTrue(_evidence_in_document(quote, self.text))
        self.assertEqual(self.extract_with_quote(quote)["fields"]["annual_revenue_rub"]["value"], 18_460_000)

    def test_tabs_replace_alignment(self):
        quote = "2110\t|\tВыручка (тыс. руб.)\t|\t18 460\t|\t15 100"
        self.assertTrue(_evidence_in_document(quote, self.text))

    def test_changed_digits_still_rejected(self):
        quote = "2110 | Выручка (тыс. руб.) | 99 460 | 15 100"
        self.assertFalse(_evidence_in_document(quote, self.text))
        result = self.extract_with_quote(quote, 99_460_000)
        self.assertIsNone(result["fields"]["annual_revenue_rub"]["value"])
        self.assertIn("annual_revenue_rub:evidence_not_in_document", result["issues"])

    def test_unsupported_amount_still_rejected_when_citation_is_valid(self):
        quote = "2110 Выручка (тыс. руб.) 18 460 15 100"
        result = self.extract_with_quote(quote, 99_460_000)
        self.assertIsNone(result["fields"]["annual_revenue_rub"]["value"])
        self.assertIn("annual_revenue_rub:amount_not_supported_by_evidence_or_units", result["issues"])

    def test_cannot_stitch_quote_from_separate_rows(self):
        source = "Выручка (тыс. руб.)\n18 460\n"
        self.assertFalse(_evidence_in_document("Выручка (тыс. руб.) 18 460", source))

    def test_empty_quote_never_supported(self):
        self.assertFalse(_evidence_in_document("", self.text))
        self.assertFalse(_evidence_in_document("  \t", self.text))

    def test_colon_or_rephrased_text_not_silently_accepted(self):
        self.assertFalse(_evidence_in_document("Выручка (тыс. руб.): 18 460", self.text))


if __name__ == "__main__":
    unittest.main()
