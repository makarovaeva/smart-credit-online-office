"""Local document -> extracted text. Independent from LLMs and loan decisions.

Modes:
- mock: use explicit fixture text, never read files;
- file: use explicit local paths passed by trusted caller;
- mixed: per document, prefer explicit file, then mock fixture.

This module does NOT fetch backend storage keys, perform OCR, verify identity,
or determine whether a credit application should be approved.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any

try:
    from pypdf.errors import PdfReadError, FileNotDecryptedError, WrongPasswordError
except ImportError:
    PdfReadError = FileNotDecryptedError = WrongPasswordError = ValueError  # pypdf remains optional until PDF parsing is requested

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 100_000
MAX_PDF_PAGES = 30
ALLOWED_SUFFIXES = frozenset({".txt", ".md", ".pdf"})


class DocumentParsingError(ValueError):
    """Controlled parse failure; a document is never considered verified."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ParseBatch:
    extracted_text_by_id: dict[str, str]
    findings: tuple[dict[str, Any], ...]


def _text_or_error(text: str, *, source: str) -> str:
    if len(text) > MAX_TEXT_CHARS:
        raise DocumentParsingError("extracted_text_too_large")
    if not text.strip():
        raise DocumentParsingError("no_readable_text_needs_ocr_or_review" if source == "file" else "empty_mock_text")
    return text


def extract_local_file(path: str | Path) -> str:
    """Extract text from a trusted local path. No network/OCR/filesystem globbing.

    `path` must be explicitly supplied by a developer/operator, NOT taken from
    a client-controlled `storage_key`, `filename`, `file_uri` or LLM response.
    """
    file = Path(path)
    if file.suffix.lower() not in ALLOWED_SUFFIXES:
        raise DocumentParsingError("unsupported_file_type")
    if not file.is_file():
        raise DocumentParsingError("file_not_found")
    if file.stat().st_size > MAX_FILE_BYTES:
        raise DocumentParsingError("file_too_large")
    try:
        if file.suffix.lower() in {".txt", ".md"}:
            text = file.read_text(encoding="utf-8-sig")
        else:
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise DocumentParsingError("pypdf_not_installed") from exc
            with file.open("rb") as stream:
                pdf = PdfReader(stream, strict=False)
                if pdf.is_encrypted:
                    raise DocumentParsingError("password_protected_pdf")
                if len(pdf.pages) > MAX_PDF_PAGES:
                    raise DocumentParsingError("pdf_too_many_pages")
                parts: list[str] = []
                total = 0
                for page in pdf.pages:
                    part = page.extract_text() or ""
                    total += len(part)
                    if total > MAX_TEXT_CHARS:
                        raise DocumentParsingError("extracted_text_too_large")
                    parts.append(part)
                text = "\n".join(parts)
        return _text_or_error(text, source="file")
    except DocumentParsingError:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, PdfReadError, FileNotDecryptedError, WrongPasswordError) as exc:
        raise DocumentParsingError("file_cannot_be_parsed") from exc


def parse_backend_documents(
    documents: Sequence[Mapping[str, Any]],
    *,
    mode: str = "mock",
    mock_text_by_id: Mapping[str, str] | None = None,
    files_by_id: Mapping[str, str | Path] | None = None,
) -> ParseBatch:
    """Return extracted text and per-document diagnostics, without full text in report.

    Known-but-unreadable documents are represented by empty text; the backend
    adapter subsequently puts them into manual review rather than counting them
    as completed or automatically requesting duplicate uploads.
    """
    if mode not in {"mock", "file", "mixed"}:
        raise ValueError("mode must be mock, file, or mixed")
    if not isinstance(documents, (list, tuple)) or len(documents) > 50:
        raise ValueError("documents must be a list with at most 50 entries")
    mock_text_by_id = mock_text_by_id or {}
    files_by_id = files_by_id or {}
    if not isinstance(mock_text_by_id, Mapping) or not isinstance(files_by_id, Mapping):
        raise ValueError("mock_text_by_id and files_by_id must be mappings")
    if mode == "mock" and files_by_id:
        raise ValueError("file paths were supplied in mock mode; use mixed or file")
    if mode == "file" and mock_text_by_id:
        raise ValueError("mock text was supplied in file mode; use mixed or mock")

    supplied_ids = {doc.get("id", doc.get("document_id")) for doc in documents if isinstance(doc, Mapping)}
    unknown_paths = set(files_by_id) - supplied_ids
    if unknown_paths:
        raise ValueError(f"file mappings refer to unknown document IDs: {sorted(unknown_paths)}")

    seen: set[str] = set()
    extracted: dict[str, str] = {}
    findings: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            raise ValueError("document metadata must be mapping")
        doc_id = doc.get("id", doc.get("document_id"))
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError("document id must be nonempty string")
        if doc_id in seen:
            raise ValueError(f"duplicate document id: {doc_id}")
        seen.add(doc_id)
        issue = None
        text = ""
        if mode in {"file", "mixed"} and doc_id in files_by_id:
            source = "file"
            path = files_by_id[doc_id]
            if not isinstance(path, (str, Path)):
                raise ValueError(f"{doc_id}: file path must be a string or Path")
            try:
                text = extract_local_file(path)
            except DocumentParsingError as exc:
                issue = exc.code
        elif mode in {"mock", "mixed"} and doc_id in mock_text_by_id:
            source = "mock"
            value = mock_text_by_id[doc_id]
            if not isinstance(value, str):
                raise ValueError(f"{doc_id}: mock text must be string")
            try:
                text = _text_or_error(value, source="mock")
            except DocumentParsingError as exc:
                issue = exc.code
        else:
            source = "none"
            issue = "no_text_source_supplied"

        extracted[doc_id] = text
        findings.append({
            "document_id": doc_id,
            "source": source,
            "status": "text_extracted" if text else "requires_review",
            "characters": len(text),
            "issue": issue,
        })
    return ParseBatch(extracted_text_by_id=extracted, findings=tuple(findings))
