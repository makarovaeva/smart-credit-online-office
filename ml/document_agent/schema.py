"""Stable I/O contracts for the document-agent prototype (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ALLOWED_TYPES = frozenset({
    "registration_extract", "financial_statements", "bank_statement",
    "collateral_proof", "kudir", "tax_declaration",
    "counterparty_contract", "charter", "other", "unknown",
})

DISPLAY_NAMES = {
    "registration_extract": "Выписка из реестра (ЕГРЮЛ/ЕГРИП)",
    "financial_statements": "Бухгалтерская или финансовая отчётность",
    "bank_statement": "Выписка по расчётному счёту",
    "collateral_proof": "Документы о праве на предмет залога",
    "kudir": "Книга учёта доходов и расходов",
    "tax_declaration": "Налоговая декларация",
    "counterparty_contract": "Договор с контрагентом",
    "charter": "Устав организации",
    "other": "Иной документ",
}


@dataclass(frozen=True)
class UploadedDocument:
    document_id: str
    filename: str
    text: str

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "UploadedDocument":
        if not isinstance(raw, dict):
            raise ValueError("Document must be an object")
        for field in ("document_id", "filename", "text"):
            if not isinstance(raw.get(field), str):
                raise ValueError(f"Document {field} must be a string")
        if not raw["document_id"].strip() or not raw["filename"].strip():
            raise ValueError("Document ID/filename cannot be empty")
        if len(raw["text"]) > 100_000:
            raise ValueError("Extracted document text exceeds MVP limit")
        return cls(document_id=raw["document_id"], filename=raw["filename"], text=raw["text"])


@dataclass(frozen=True)
class DocumentAnalysis:
    document_type: str
    borrower_id: str | None
    evidence: tuple[str, ...]
    requires_review: bool

    @classmethod
    def from_json(cls, raw: Any) -> "DocumentAnalysis":
        if not isinstance(raw, dict):
            raise ValueError("LLM result must be JSON object")
        doc_type = raw.get("document_type")
        if not isinstance(doc_type, str) or doc_type not in ALLOWED_TYPES:
            raise ValueError(f"Unsupported document type: {doc_type!r}")
        borrower_id = raw.get("borrower_id")
        if borrower_id is not None and (not isinstance(borrower_id, str) or not borrower_id.strip()):
            raise ValueError("borrower_id must be nonempty string or null")
        evidence = raw.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) > 5 or any(
            not isinstance(e, str) or len(e) > 250 for e in evidence
        ):
            raise ValueError("evidence must be at most five short strings")
        flag = raw.get("requires_review", False)
        if not isinstance(flag, bool):
            raise ValueError("requires_review must be a boolean")
        return cls(doc_type, borrower_id, tuple(evidence), flag)


def _assert_schema(batch: dict[str, Any]) -> tuple[dict, dict, list[UploadedDocument]]:
    """Validate minimal input and cross IDs against existing synthetic_data conventions."""
    if not isinstance(batch, dict):
        raise ValueError("Input must be a JSON object")
    application, borrower = batch.get("application"), batch.get("borrower")
    if not isinstance(application, dict) or not isinstance(borrower, dict):
        raise ValueError("application and borrower must be objects")
    if not isinstance(application.get("application_id"), str) or not application["application_id"]:
        raise ValueError("application_id required")
    borrower_id = application.get("borrower_id")
    if not isinstance(borrower_id, str) or not borrower_id:
        raise ValueError("application.borrower_id required")
    if borrower.get("borrower_id") != borrower_id:
        raise ValueError("Application/borrower IDs do not match")
    form = borrower.get("company", {}).get("legal_form") if isinstance(borrower.get("company"), dict) else None
    if form not in ("ooo", "ip"):
        raise ValueError("Expected borrower.company.legal_form = ooo or ip")
    raw_documents = batch.get("documents")
    if not isinstance(raw_documents, list) or len(raw_documents) > 20:
        raise ValueError("documents must be a list with at most 20 entries")
    docs = [UploadedDocument.from_json(doc) for doc in raw_documents]
    if len({doc.document_id for doc in docs}) != len(docs):
        raise ValueError("Repeated document_id")
    return application, borrower, docs

# ---------------- Financial field extraction, v0.5 ----------------
# These contracts deliberately do not contain credit decisions or credit scores.
from datetime import date as _date
import re as _re

# Keep field definitions explicit: model cannot silently invent new columns.
FIELD_KINDS = {
    "company_inn": "inn",
    "period_from": "date",
    "period_to": "date",
    "annual_revenue_rub": "amount",
    "bank_inflows_rub": "amount",
    "kudir_income_rub": "amount",
    "taxable_income_rub": "amount",
    "net_profit_rub": "amount",
    "ebitda_rub": "amount",
}


@dataclass(frozen=True)
class EvidenceValue:
    value: str | int | None
    evidence: str | None

    @classmethod
    def from_json(cls, raw: Any, *, name: str) -> "EvidenceValue":
        if not isinstance(raw, dict) or set(raw) != {"value", "evidence"}:
            raise ValueError(f"{name} must contain only value and evidence")
        value, evidence = raw["value"], raw["evidence"]
        if value is None:
            if evidence is not None:
                raise ValueError(f"{name}: null value requires null evidence")
            return cls(None, None)
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 240:
            raise ValueError(f"{name}: non-null value requires short exact evidence")
        kind = FIELD_KINDS[name]
        if kind == "amount":
            if type(value) is not int or abs(value) > 10**13:
                raise ValueError(f"{name}: expected integer ruble amount")
        elif kind == "inn":
            if not isinstance(value, str) or not _re.fullmatch(r"\d{10}|\d{12}", value):
                raise ValueError(f"{name}: invalid INN")
        elif kind == "date":
            if not isinstance(value, str):
                raise ValueError(f"{name}: date must be ISO string")
            try:
                if _date.fromisoformat(value).isoformat() != value:
                    raise ValueError("non-canonical date")
            except ValueError as exc:
                raise ValueError(f"{name}: date must be YYYY-MM-DD") from exc
        return cls(value, evidence)


@dataclass(frozen=True)
class DocumentFieldAnalysis:
    document_type: str
    fields: dict[str, EvidenceValue]
    requires_review: bool

    @classmethod
    def from_json(cls, raw: Any) -> "DocumentFieldAnalysis":
        if not isinstance(raw, dict) or set(raw) != {"document_type", "fields", "requires_review"}:
            raise ValueError("Field extraction JSON requires document_type, fields, requires_review")
        kind = raw["document_type"]
        if kind not in ALLOWED_TYPES:
            raise ValueError("Invalid document_type")
        if type(raw["requires_review"]) is not bool:
            raise ValueError("requires_review must be boolean")
        values = raw["fields"]
        if not isinstance(values, dict) or set(values) - set(FIELD_KINDS):
            raise ValueError("Unexpected field name in extraction")
        # Missing keys are interpreted as null (some providers omit absent keys).
        fields = {
            name: EvidenceValue.from_json(values.get(name, {"value": None, "evidence": None}), name=name)
            for name in FIELD_KINDS
        }
        a, b = fields["period_from"].value, fields["period_to"].value
        if isinstance(a, str) and isinstance(b, str) and a > b:
            raise ValueError("Document period starts after its end")
        return cls(kind, fields, raw["requires_review"])
