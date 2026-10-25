"""Deterministic checklist and explainable reconciliation, no autonomous decisions."""
from __future__ import annotations

from typing import Any

from .providers import LLMProvider
from .rules import required_documents, customer_request
from .schema import DISPLAY_NAMES, DocumentAnalysis, UploadedDocument, _assert_schema


def inspect_package(batch: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    application, borrower, docs = _assert_schema(batch)
    required = required_documents(application, borrower)
    recognized: set[str] = set()
    details = []
    review = False

    for doc in docs:
        if not doc.text.strip():
            result = DocumentAnalysis("unknown", None, (), True)
            issue = "no_extracted_text"
        else:
            try:
                result = provider.analyze(doc)
                # Defensive validation even for custom provider implementations.
                result = DocumentAnalysis.from_json({
                    "document_type": result.document_type,
                    "borrower_id": result.borrower_id,
                    "evidence": list(result.evidence),
                    "requires_review": result.requires_review,
                })
                issue = None
            except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
                # No confident classification in case of transient/invalid provider output.
                result = DocumentAnalysis("unknown", None, (), True)
                issue = "analysis_failed"  # Never leak the document or API secret.
        issues = [issue] if issue else []
        if result.borrower_id and result.borrower_id not in doc.text:
            issues.append("unsubstantiated_borrower_id")
        if result.borrower_id and result.borrower_id != application["borrower_id"]:
            issues.append("borrower_id_mismatch")
        if result.document_type != "unknown" and (
            not result.evidence or any(snippet not in doc.text for snippet in result.evidence)
        ):
            issues.append("unsupported_classification_evidence")
        if result.document_type == "unknown":
            issues.append("unrecognized_document")
        if result.requires_review:
            issues.append("provider_requests_review")
        if issues:
            review = True
        # A known type with mismatch/review does not satisfy completeness.
        if not issues:
            recognized.add(result.document_type)
        details.append({
            "document_id": doc.document_id,
            "filename": doc.filename,
            "detected_type": result.document_type,
            "evidence": list(result.evidence),
            "issues": sorted(set(issues)),
        })

    missing = [kind for kind in required if kind not in recognized]
    status = "needs_documents" if missing else ("requires_review" if review else "package_complete_provisional")
    return {
        "application_id": application["application_id"],
        "borrower_id": application["borrower_id"],
        "status": status,
        "policy_version": "demo_document_rules_v0.1",
        "required_document_types": required,
        "missing_document_types": missing,
        "missing_documents": [{"type": kind, "name": DISPLAY_NAMES[kind]} for kind in missing],
        "documents": details,
        "requires_human_review": review,
        "customer_message": customer_request(missing, review),
        "disclaimer": "Demo completeness only; authenticity and credit approval are NOT verified.",
    }
