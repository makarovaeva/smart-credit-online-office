"""Document review adapter for the current FastAPI backend (MVP).

This module is intentionally PURE: it does not import backend ORM, move application
statuses, create info_requests, approve loans, or invoke credit_policy. Call it with
already-authorized DTO dictionaries and text obtained from a separate OCR layer.

The backend owns document requirements, orchestration, persistence and all lending
policy/decisions. A successful result means *provisional completeness*, never loan
approval or document authenticity.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
import re
from typing import Any

from .providers import LLMProvider
from .schema import DocumentAnalysis, UploadedDocument

SUPPORTED_CLASSIFICATIONS = frozenset({
    "registration_extract", "financial_statements", "bank_statement", "collateral_proof",
})


def _id(value: Any, name: str) -> str:
    result = str(value).strip() if value is not None else ""
    if not result or result == "None":
        raise ValueError(f"{name} is required")
    return result


def _requirements(items: Sequence[str | Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(items, (list, tuple)):
        raise ValueError("requirements must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        value: Mapping[str, Any] = {"document_type": item} if isinstance(item, str) else item
        if not isinstance(value, Mapping):
            raise ValueError("requirement must be a document type or mapping")
        kind = value.get("document_type") or value.get("type")
        if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", kind):
            raise ValueError(f"invalid required document type: {kind!r}")
        if kind in seen:
            raise ValueError(f"duplicate required document type: {kind}")
        seen.add(kind)
        start, end = value.get("period_from"), value.get("period_to")
        if (start is None) != (end is None):
            raise ValueError(f"requirement {kind}: both period bounds must be given")
        if start is not None:
            start, end = str(start), str(end)
            if date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError(f"requirement {kind}: period_from after period_to")
        result.append({"document_type": kind, "period_from": start, "period_to": end})
    return result


def _inn_present(text: str, inn: str) -> bool:
    """A weak identity consistency check, NOT evidence of ownership/authenticity."""
    return bool(re.search(r"(?<!\d)" + re.escape(inn) + r"(?!\d)", text))


def _covers_period(doc: Mapping[str, Any], requirement: Mapping[str, Any]) -> bool | None:
    if requirement["period_from"] is None:
        return True
    start, end = doc.get("period_from"), doc.get("period_to")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(str(start)) <= date.fromisoformat(requirement["period_from"])
                and date.fromisoformat(str(end)) >= date.fromisoformat(requirement["period_to"]))
    except (TypeError, ValueError):
        return None


def review_backend_package(
    *,
    application: Mapping[str, Any],
    company: Mapping[str, Any],
    documents: Sequence[Mapping[str, Any]],
    extracted_text_by_id: Mapping[str, str],
    requirements: Sequence[str | Mapping[str, Any]],
    provider: LLMProvider,
) -> dict[str, Any]:
    """Return review findings and an *unpersisted* info_request draft.

    `requirements` come from BACKEND-approved policy, not the language model.
    `documents` are backend document metadata; binary files are NOT loaded here.
    `extracted_text_by_id` is supplied by an OCR/text extraction stage.
    The LLM's classification MUST have literal supporting evidence in that text.
    """
    if not isinstance(application, Mapping) or not isinstance(company, Mapping):
        raise ValueError("application and company must be mappings")
    app_id = _id(application.get("id", application.get("application_id")), "application.id")
    company_id = _id(company.get("id", company.get("borrower_id")), "company.id")
    related = application.get("company_id", application.get("borrower_id"))
    if related is None or str(related) != company_id:
        raise ValueError("application.company_id and company.id do not match")
    inn = company.get("inn")
    if not isinstance(inn, str) or not re.fullmatch(r"\d{10}|\d{12}", inn):
        raise ValueError("company.inn must contain 10 or 12 digits")
    if not isinstance(documents, (list, tuple)) or len(documents) > 50:
        raise ValueError("documents must be a list of at most 50 entries")
    if not isinstance(extracted_text_by_id, Mapping):
        raise ValueError("extracted_text_by_id must be a mapping")
    reqs = _requirements(requirements)
    req_by_type = {r["document_type"]: r for r in reqs}
    document_findings: list[dict[str, Any]] = []
    accepted: set[str] = set()
    claimed_uploaded: set[str] = set()
    seen_ids: set[str] = set()
    for doc in documents:
        if not isinstance(doc, Mapping):
            raise ValueError("document metadata must be a mapping")
        doc_id = _id(doc.get("id", doc.get("document_id")), "document.id")
        if doc_id in seen_ids:
            raise ValueError(f"duplicate document id: {doc_id}")
        seen_ids.add(doc_id)
        linked_app = doc.get("application_id")
        if linked_app is not None and str(linked_app) != app_id:
            raise ValueError(f"document {doc_id} belongs to a different application")
        declared_type = doc.get("type", doc.get("document_type"))
        if isinstance(declared_type, str) and declared_type in req_by_type:
            claimed_uploaded.add(declared_type)
        text = extracted_text_by_id.get(doc_id, "")
        if not isinstance(text, str) or len(text) > 100_000:
            raise ValueError(f"document {doc_id}: invalid/oversized extracted text")
        filename = str(doc.get("filename", doc.get("file_name", f"{doc_id}.txt")))
        issues: list[str] = []
        detected_type = "unknown"
        evidence: list[str] = []
        if not text.strip():
            issues.append("text_unavailable")
        else:
            try:
                analysis = provider.analyze(UploadedDocument(doc_id, filename, text))
                # Validate again, including when a custom provider is injected.
                analysis = DocumentAnalysis.from_json({
                    "document_type": analysis.document_type,
                    "borrower_id": analysis.borrower_id,
                    "evidence": list(analysis.evidence),
                    "requires_review": analysis.requires_review,
                })
                detected_type = analysis.document_type
                evidence = list(analysis.evidence)
                if detected_type == "unknown":
                    issues.append("unrecognized_document")
                elif not evidence or any(fragment not in text for fragment in evidence):
                    issues.append("evidence_unsubstantiated")
                if analysis.requires_review:
                    issues.append("provider_requires_review")
                # The old provider's borrower_id field is intentionally not used:
                # bank documents contain INN/OGRN, not internal application UUIDs.
                if detected_type in req_by_type and not _inn_present(text, inn):
                    issues.append("company_inn_not_confirmed")
            except (ValueError, TypeError, KeyError, OSError, IndexError):
                issues.append("model_analysis_failed")
        if detected_type in req_by_type:
            r = req_by_type[detected_type]
            cover = _covers_period(doc, r)
            if cover is False:
                issues.append("period_insufficient")
            elif cover is None:
                issues.append("period_unknown")
            elif r["period_from"] is not None:
                # Existing metadata may be user-declared; OCR has not verified dates.
                issues.append("period_not_verified_in_document_text")
        # Do not treat uploaded file or type label as verified evidence.
        if detected_type in req_by_type and not issues:
            accepted.add(detected_type)
        document_findings.append({
            "document_id": doc_id,
            "declared_type": declared_type,
            "detected_type": detected_type,
            "issues": sorted(set(issues)),
            "evidence": evidence,
            "provisionally_accepted": detected_type in req_by_type and not issues,
        })
    # A document already uploaded but unverified is for review, not an automatic
    # request for the customer to upload the very same file again.
    pending_uploaded = (claimed_uploaded | {
        f["detected_type"] for f in document_findings if f["detected_type"] in req_by_type
    }) - accepted
    missing = [r["document_type"] for r in reqs if r["document_type"] not in accepted | pending_uploaded]
    unverified = [r["document_type"] for r in reqs if r["document_type"] in pending_uploaded]
    other_issues = any(f["issues"] for f in document_findings)
    needs_review = bool(unverified or other_issues)
    status = "needs_documents" if missing else ("requires_review" if needs_review else "package_complete_provisional")
    draft = None
    if missing:
        draft = {
            "message": "Для продолжения проверки документов предоставьте: " + ", ".join(missing) + ".",
            "requested_document_types": missing,
        }
    return {
        "application_id": app_id,
        "company_id": company_id,
        "status": status,  # DOCUMENT REVIEW ONLY, NOT applications.status!
        "required_document_types": [r["document_type"] for r in reqs],
        "missing_document_types": missing,
        "unverified_document_types": unverified,
        "requires_human_review": needs_review,
        "document_findings": document_findings,
        "info_request_draft": draft,  # not persisted: backend validates and decides
        "disclaimer": "No document authenticity verified; no scoring or credit decision performed.",
    }
