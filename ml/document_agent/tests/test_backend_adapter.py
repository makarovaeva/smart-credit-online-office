"""Focused unit tests for the pure backend document adapter."""
import unittest

from ml.document_agent.backend_adapter import review_backend_package
from ml.document_agent.providers import StaticDemoProvider


APP = {"id": "app-1", "company_id": "co-1", "requested_amount": 3_000_000}
COMPANY = {"id": "co-1", "inn": "7701234567", "legal_form": "ooo"}


def check(documents=(), responses=None, texts=None, requirements=("bank_statement",)):
    return review_backend_package(
        application=APP, company=COMPANY, documents=list(documents),
        extracted_text_by_id=texts or {}, requirements=list(requirements),
        provider=StaticDemoProvider(responses or {}),
    )


class BackendAdapterTests(unittest.TestCase):
    def test_missing_creates_draft_but_no_decision(self):
        result = check()
        self.assertEqual(result["status"], "needs_documents")
        self.assertEqual(result["info_request_draft"]["requested_document_types"], ["bank_statement"])
        self.assertNotIn("decision", result)
        self.assertNotIn("route", result)
        self.assertNotIn("application_status", result)

    def test_good_document_is_provisionally_complete_only(self):
        result = check(
            documents=[{"id": "doc-1", "application_id": "app-1", "type": "bank_statement"}],
            texts={"doc-1": "Выписка с расчётного счёта ИНН 7701234567"},
            responses={"doc-1": {"document_type": "bank_statement", "borrower_id": None,
                                 "evidence": ["Выписка с расчётного счёта"], "requires_review": False}},
        )
        self.assertEqual(result["status"], "package_complete_provisional")
        self.assertIsNone(result["info_request_draft"])
        self.assertTrue(result["document_findings"][0]["provisionally_accepted"])

    def test_uploaded_but_no_ocr_goes_to_review_without_duplicate_request(self):
        result = check(documents=[{"id": "doc-1", "type": "bank_statement"}])
        self.assertEqual(result["status"], "requires_review")
        self.assertEqual(result["missing_document_types"], [])
        self.assertEqual(result["unverified_document_types"], ["bank_statement"])
        self.assertIsNone(result["info_request_draft"])

    def test_bad_evidence_does_not_count(self):
        result = check(documents=[{"id": "doc-1", "type": "bank_statement"}],
                       texts={"doc-1": "ИНН 7701234567"},
                       responses={"doc-1": {"document_type": "bank_statement", "borrower_id": None,
                                            "evidence": ["несуществующая выписка"], "requires_review": False}})
        self.assertEqual(result["status"], "requires_review")
        self.assertIn("evidence_unsubstantiated", result["document_findings"][0]["issues"])

    def test_expected_inn_missing_review(self):
        result = check(documents=[{"id": "doc-1", "type": "bank_statement"}],
                       texts={"doc-1": "Выписка 7700000000"},
                       responses={"doc-1": {"document_type": "bank_statement", "borrower_id": None,
                                            "evidence": ["Выписка"], "requires_review": False}})
        self.assertIn("company_inn_not_confirmed", result["document_findings"][0]["issues"])
        self.assertTrue(result["requires_human_review"])

    def test_period_metadata_only_requires_review(self):
        result = check(
            documents=[{"id": "doc-1", "type": "bank_statement", "period_from": "2025-01-01", "period_to": "2025-12-31"}],
            texts={"doc-1": "Выписка по счёту ИНН 7701234567"},
            responses={"doc-1": {"document_type": "bank_statement", "borrower_id": None,
                                 "evidence": ["Выписка"], "requires_review": False}},
            requirements=[{"document_type": "bank_statement", "period_from": "2025-01-01", "period_to": "2025-12-31"}],
        )
        self.assertIn("period_not_verified_in_document_text", result["document_findings"][0]["issues"])
        self.assertEqual(result["status"], "requires_review")

    def test_rejects_foreign_company(self):
        with self.assertRaises(ValueError):
            review_backend_package(application=APP, company={"id": "different", "inn": "7701234567"},
                                   documents=[], extracted_text_by_id={}, requirements=[],
                                   provider=StaticDemoProvider({}))

    def test_rejects_foreign_document(self):
        with self.assertRaises(ValueError):
            check(documents=[{"id": "d1", "application_id": "other", "type": "bank_statement"}])

    def test_requires_are_supplied_by_backend_not_agent_rules(self):
        result = check(requirements=[])
        self.assertEqual(result["required_document_types"], [])
        self.assertEqual(result["status"], "package_complete_provisional")
        self.assertIsNone(result["info_request_draft"])

    def test_unknown_backend_document_type_is_not_falsely_verified(self):
        result = check(requirements=["tax_declaration"], documents=[{"id": "d1", "type": "tax_declaration"}])
        self.assertEqual(result["unverified_document_types"], ["tax_declaration"])
        self.assertTrue(result["requires_human_review"])


if __name__ == "__main__":
    unittest.main()
