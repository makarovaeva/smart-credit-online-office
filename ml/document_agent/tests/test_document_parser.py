import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ml.document_agent.document_parser import (
    DocumentParsingError, extract_local_file, parse_backend_documents,
)
from ml.document_agent.main import run_review
from ml.document_agent.providers import StaticDemoProvider

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def payload():
    return json.loads((EXAMPLES / "backend_input.json").read_text(encoding="utf-8"))


class FileParserTests(unittest.TestCase):
    def test_mock_mode_does_not_read_disk(self):
        result = parse_backend_documents(payload()["documents"], mode="mock",
                                         mock_text_by_id=payload()["mock_text_by_id"])
        self.assertEqual(result.findings[0]["source"], "mock")
        self.assertIn("7701234567", result.extracted_text_by_id["doc-bank-1"])

    def test_file_mode_reads_separate_text_file(self):
        result = parse_backend_documents(payload()["documents"], mode="file",
                                         files_by_id={"doc-bank-1": EXAMPLES / "bank_statement.txt"})
        self.assertEqual(result.findings[0]["source"], "file")
        self.assertEqual(result.findings[0]["status"], "text_extracted")
        self.assertNotIn("text", result.findings[0])  # never expose raw contents in report

    def test_mixed_prefers_real_file_over_fixture(self):
        result = parse_backend_documents(payload()["documents"], mode="mixed",
                                         mock_text_by_id={"doc-bank-1": "fake"},
                                         files_by_id={"doc-bank-1": EXAMPLES / "bank_statement.txt"})
        self.assertIn("7701234567", result.extracted_text_by_id["doc-bank-1"])

    def test_missing_file_fails_closed_as_review(self):
        result = parse_backend_documents(payload()["documents"], mode="file",
                                         files_by_id={"doc-bank-1": "does_not_exist.txt"})
        self.assertEqual(result.extracted_text_by_id["doc-bank-1"], "")
        self.assertEqual(result.findings[0]["issue"], "file_not_found")
        self.assertEqual(result.findings[0]["status"], "requires_review")

    def test_unsupported_file_type(self):
        with self.assertRaisesRegex(DocumentParsingError, "unsupported_file_type"):
            extract_local_file("/tmp/some_image.png")

    def test_empty_file_needs_ocr_or_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "empty.txt"
            path.write_text("  ", encoding="utf-8")
            with self.assertRaisesRegex(DocumentParsingError, "no_readable_text"):
                extract_local_file(path)

    def test_text_file_size_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.txt"
            path.write_bytes(b"a" * (10 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(DocumentParsingError, "file_too_large"):
                extract_local_file(path)

    def test_invalid_document_id_rejected(self):
        with self.assertRaises(ValueError):
            parse_backend_documents([{"id": "d1"}, {"id": "d1"}])

    def test_mock_not_used_when_file_mode_selected(self):
        # End-to-end helper strips mock text for explicit file-only mode.
        raw = payload()
        result = run_review(raw, provider=StaticDemoProvider(raw["mock_responses"]),
                            parser_mode="file", files_by_id={"doc-bank-1": str(EXAMPLES / "bank_statement.txt")})
        self.assertEqual(result["parsing"][0]["source"], "file")
        self.assertEqual(result["status"], "needs_documents")
        self.assertEqual(result["missing_document_types"], ["financial_statements"])
        self.assertNotIn("decision", result)

    def test_mock_pipeline_missing_doc_creates_only_draft(self):
        raw = payload()
        result = run_review(raw, provider=StaticDemoProvider(raw["mock_responses"]))
        self.assertEqual(result["status"], "needs_documents")
        self.assertEqual(result["missing_document_types"], ["financial_statements"])
        self.assertEqual(result["info_request_draft"]["requested_document_types"], ["financial_statements"])
        self.assertIsNone(result.get("credit_decision"))
        self.assertNotIn("application_status", result)

    def test_unreadable_uploaded_document_is_review_not_missing(self):
        raw = payload()
        raw["requirements"] = ["bank_statement"]
        result = run_review(raw, provider=StaticDemoProvider(raw["mock_responses"]),
                            parser_mode="file", files_by_id={"doc-bank-1": "missing.pdf"})
        self.assertEqual(result["status"], "requires_review")
        self.assertEqual(result["missing_document_types"], [])
        self.assertEqual(result["unverified_document_types"], ["bank_statement"])

    def test_extended_backend_document_type(self):
        raw = payload()
        raw["requirements"] = ["tax_declaration"]
        raw["documents"] = [{"id": "tax-1", "type": "tax_declaration"}]
        raw["mock_text_by_id"] = {"tax-1": "Налоговая декларация ИНН 7701234567"}
        raw["mock_responses"] = {"tax-1": {
            "document_type": "tax_declaration", "borrower_id": None,
            "evidence": ["Налоговая декларация"], "requires_review": False,
        }}
        result = run_review(raw, provider=StaticDemoProvider(raw["mock_responses"]))
        self.assertEqual(result["status"], "package_complete_provisional")

    def test_missing_backend_requirements_is_error(self):
        raw = payload()
        del raw["requirements"]
        with self.assertRaisesRegex(ValueError, "requires explicit requirements"):
            run_review(raw, provider=StaticDemoProvider(raw["mock_responses"]))

    def test_full_mock_package_complete_provisional(self):
        raw = json.loads((EXAMPLES / "backend_complete_input.json").read_text(encoding="utf-8"))
        result = run_review(raw, provider=StaticDemoProvider(raw["mock_responses"]))
        self.assertEqual(result["status"], "package_complete_provisional")
        self.assertIsNone(result["info_request_draft"])
        self.assertNotIn("decision", result)

    def test_pdf_text_extraction(self):
        try:
            from reportlab.pdfgen import canvas
            import pypdf
        except ImportError:
            self.skipTest("optional pypdf/reportlab not installed")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.pdf"
            c = canvas.Canvas(str(path))
            c.drawString(72, 750, "Bank statement INN 7701234567")
            c.save()
            self.assertIn("7701234567", extract_local_file(path))

    def test_scanned_pdf_no_text_does_not_become_accepted(self):
        try:
            from reportlab.pdfgen import canvas
            import pypdf
        except ImportError:
            self.skipTest("optional pypdf/reportlab not installed")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.pdf"
            c = canvas.Canvas(str(path))
            c.showPage()
            c.save()
            with self.assertRaisesRegex(DocumentParsingError, "no_readable_text"):
                extract_local_file(path)


if __name__ == "__main__":
    unittest.main()
