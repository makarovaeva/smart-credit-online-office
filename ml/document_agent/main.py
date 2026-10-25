"""CLI for demo rules and backend-oriented document review.

Run from repo root: python -m ml.document_agent.main --mode backend ...
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .backend_adapter import review_backend_package
from .document_parser import parse_backend_documents
from .providers import StaticDemoProvider, OpenAICompatibleProvider
from .service import inspect_package
from .field_extractor import extract_verified_fields
from .schema import UploadedDocument


def _parse_file_options(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--file must be DOC_ID=PATH")
        doc_id, filepath = value.split("=", 1)
        if not doc_id.strip() or not filepath.strip() or doc_id in result:
            raise ValueError("--file requires unique nonempty DOC_ID=PATH")
        result[doc_id] = filepath
    return result


def run_review(
    raw: dict[str, Any], *, provider: Any, mode: str = "backend", parser_mode: str = "mock",
    files_by_id: dict[str, str] | None = None,
    extract_fields: bool = False,
) -> dict[str, Any]:
    """Pure orchestration; does not access backend DB, policies or app statuses."""
    if mode == "demo":
        if files_by_id:
            raise ValueError("--file is available only for --mode backend")
        return inspect_package(raw, provider)
    if mode != "backend":
        raise ValueError("mode must be demo or backend")
    if "requirements" not in raw:
        raise ValueError("backend mode requires explicit requirements from backend")
    docs = raw.get("documents", [])
    parsed = parse_backend_documents(
        docs, mode=parser_mode, mock_text_by_id=raw.get("mock_text_by_id", {}) if parser_mode != "file" else {},
        files_by_id=files_by_id,
    )
    result = review_backend_package(
        application=raw["application"],
        company=raw["company"],
        documents=docs,
        extracted_text_by_id=parsed.extracted_text_by_id,
        requirements=raw.get("requirements", []),
        provider=provider,
    )
    result["parsing"] = list(parsed.findings)
    if extract_fields:
        expected_inn = raw["company"].get("inn")
        result["field_extractions"] = [
            extract_verified_fields(
                UploadedDocument(
                    document_id=str(doc.get("id", doc.get("document_id"))),
                    filename=str(doc.get("filename", doc.get("file_name", "unknown.txt"))),
                    text=parsed.extracted_text_by_id.get(str(doc.get("id", doc.get("document_id"))), ""),
                ),
                provider,
                expected_inn=expected_inn,
            )
            for doc in docs
        ]
        # Field issues are informative, NOT lending decisions and do not alter
        # the backend's document requirements or application state.
        result["field_extraction_review_required"] = any(
            f["requires_review"] for f in result["field_extractions"]
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Document review; never approves or rejects loans")
    parser.add_argument("--input", required=True, help="Local JSON containing an application and document metadata")
    parser.add_argument("--out", required=True, help="Output review JSON path")
    parser.add_argument("--mode", choices=("demo", "backend"), default="backend")
    parser.add_argument("--parser", choices=("mock", "file", "mixed"), default="mock")
    parser.add_argument("--file", action="append", default=[], metavar="DOC_ID=PATH",
                        help="Use an explicit local .txt/.md/.pdf path for this document; repeatable")
    parser.add_argument("--provider", choices=("mock", "compatible"), default="mock")
    parser.add_argument("--extract-fields", action="store_true",
                        help="Also extract evidenced financial fields; never changes credit policy")
    parser.add_argument("--base-url", help="Trusted OpenAI-compatible base URL or DOCUMENT_LLM_BASE_URL")
    parser.add_argument("--model", help="Model ID or DOCUMENT_LLM_MODEL")
    args = parser.parse_args()
    try:
        files_by_id = _parse_file_options(args.file)
    except ValueError as exc:
        parser.error(str(exc))
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        parser.error("--input must contain a JSON object")
    if args.provider == "mock":
        provider = StaticDemoProvider(raw.get("mock_responses", {}),
                                      field_responses=raw.get("mock_field_responses", {}))
    else:
        base_url = args.base_url or os.environ.get("DOCUMENT_LLM_BASE_URL")
        model = args.model or os.environ.get("DOCUMENT_LLM_MODEL")
        if not base_url or not model:
            parser.error("compatible provider requires --base-url and --model, or env variables")
        provider = OpenAICompatibleProvider(base_url=base_url, model=model)
    result = run_review(raw, provider=provider, mode=args.mode,
                        parser_mode=args.parser, files_by_id=files_by_id,
                        extract_fields=args.extract_fields)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Document review written to {out} (status: {result['status']})")


if __name__ == "__main__":
    main()
