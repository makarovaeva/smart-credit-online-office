"""Evidence-checked financial field extraction from already parsed text.

The LLM proposes fields. Python validates types, verbatim quotes, dates and
currency magnitudes. It NEVER changes an application status or lending decision.

CLI: python -m ml.document_agent.field_extractor --provider mock|compatible
     --cases ml/document_agent/examples/realistic/cases.json --out ...
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError

from .document_parser import extract_local_file
from .providers import OpenAICompatibleProvider, StaticDemoProvider
from .schema import DocumentFieldAnalysis, FIELD_KINDS, UploadedDocument

_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)|(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
_NUMBER_RE = re.compile(
    r"(?<!\d)[+\-−]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?!\d)"
)


def _safe_failure_info(exc: Exception) -> dict[str, Any]:
    """Report only allowlisted error categories, never model text, URL, or secrets.

    No exception text, HTTP headers, body, document data or credentials
    are included in the report.
    """
    if isinstance(exc, HTTPError):
        return {"failure_kind": "http_error", "http_status": int(exc.code)}
    if isinstance(exc, URLError):
        return {"failure_kind": "connection_error"}
    if isinstance(exc, TimeoutError):
        return {"failure_kind": "timeout"}
    if isinstance(exc, json.JSONDecodeError):
        return {"failure_kind": "invalid_json"}
    if isinstance(exc, ValueError):
        message = str(exc)
        if "Field extraction JSON requires" in message:
            reason = "unexpected_top_level_json_keys"
        elif "Unexpected field name" in message:
            reason = "unknown_field_names"
        elif "integer ruble amount" in message:
            reason = "incorrect_amount_type"
        elif "short exact evidence" in message or "null evidence" in message:
            reason = "evidence_schema_invalid"
        elif "date must" in message or "non-canonical date" in message:
            reason = "date_schema_invalid"
        elif "invalid INN" in message:
            reason = "inn_schema_invalid"
        elif "Invalid document_type" in message:
            reason = "document_type_schema_invalid"
        elif "Expected text content" in message:
            reason = "missing_text_response"
        elif "Document period starts" in message:
            reason = "invalid_period"
        elif "must contain only value and evidence" in message:
            reason = "unexpected_field_json_keys"
        elif "requires_review must" in message:
            reason = "invalid_review_flag"
        elif "LLM response too large" in message:
            reason = "response_too_large"
        else:
            reason = "other_schema_error"
        return {"failure_kind": "invalid_model_schema", "failure_reason": reason}
    if isinstance(exc, (KeyError, IndexError, TypeError, AttributeError)):
        return {"failure_kind": "unexpected_api_response_structure"}
    if isinstance(exc, OSError):
        return {"failure_kind": "connection_error"}
    return {"failure_kind": "unknown_failure"}


class FieldProvider(Protocol):
    def extract_fields(self, document: UploadedDocument) -> DocumentFieldAnalysis: ...


def _date_values(quote: str) -> set[str]:
    found = set()
    for match in _DATE_RE.finditer(quote):
        try:
            if match.group(1):
                value = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            else:
                value = date(int(match.group(6)), int(match.group(5)), int(match.group(4)))
            found.add(value.isoformat())
        except ValueError:
            continue
    return found


def _normalize_evidence_spacing(text: str) -> str:
    """Normalize presentation whitespace, not factual content.

    A pipe is a *table column separator*, so it may be written as a space
    in an LLM quote. Digits, punctuation, signs, and words remain unchanged.
    """
    without_pipes = re.sub(r"\s*\|\s*", " ", text)
    return re.sub(r"[\s\u00a0\u202f]+", " ", without_pipes).strip()


def _evidence_in_document(quote: str, document_text: str) -> bool:
    """Accept spacing variants within ONE source line, not fabricated facts.

    Deliberately do not join different lines: a citation must not borrow a
    label from one table row and a number from the next row. Verbatim quotes
    (including genuine multi-line quotations) remain supported.
    """
    if not quote.strip():
        return False
    if quote in document_text:
        return True
    normalized_quote = _normalize_evidence_spacing(quote)
    return any(
        normalized_quote in _normalize_evidence_spacing(line)
        for line in document_text.splitlines()
    )


def _amount_in_quote(amount_rub: int, quote: str) -> bool:
    # Source evidence must literally support the amount. Unit conversion is
    # allowed ONLY when explicitly marked: 'тыс. руб.' or 'млн руб.'.
    lower = quote.lower()
    if re.search(r"\bмлн\.?\s*(?:руб|₽)|\bмиллион", lower):
        multiplier = 1_000_000
    elif re.search(r"\bтыс\.?\s*(?:руб|₽)|\bтысяч", lower):
        multiplier = 1_000
    else:
        multiplier = 1
    for match in _NUMBER_RE.finditer(quote):
        value = match.group().replace(" ", "").replace("\u00a0", "").replace("\u202f", "").replace("−", "-")
        try:
            # Russian decimal comma (or decimal point), but not grouping dots.
            number = float(value.replace(",", "."))
        except ValueError:
            continue
        if abs(number * multiplier - amount_rub) < 0.005:
            return True
    return False


def extract_verified_fields(
    document: UploadedDocument,
    provider: FieldProvider,
    *,
    expected_inn: str | None = None,
) -> dict[str, Any]:
    """Do not trust model schema or evidence solely because API returned HTTP 200.

    Invalid individual fields are dropped, with explainable issues. A transport
    or schema error produces review-required output, not false success.
    """
    output: dict[str, Any] = {
        "document_id": document.document_id,
        "document_type": "unknown",
        "fields": {},
        "issues": [],
        "requires_review": True,
    }
    if len(document.text) > 100_000 or not document.text.strip():
        output["issues"].append("no_readable_text_or_too_large")
        return output
    try:
        proposed = provider.extract_fields(document)
        # Schema validation is performed again even for user-supplied providers.
        proposed = DocumentFieldAnalysis.from_json({
            "document_type": proposed.document_type,
            "fields": {k: {"value": v.value, "evidence": v.evidence} for k, v in proposed.fields.items()},
            "requires_review": proposed.requires_review,
        })
    except (ValueError, TypeError, KeyError, IndexError, OSError, AttributeError, TimeoutError) as exc:
        output["issues"].append("model_extraction_failed")
        output["diagnostic"] = _safe_failure_info(exc)
        return output

    output["document_type"] = proposed.document_type
    # A document containing an explicit instruction addressed to an AI is
    # untrusted and must be reviewed even if financial values were recovered.
    if re.search(r"инструкци[яию]\s+для\s+(?:ai|ии)|ignore\s+(?:previous|system)\s+instructions|игнорируй\s+системн", document.text, re.IGNORECASE):
        output["issues"].append("possible_prompt_injection")
    if proposed.requires_review:
        output["issues"].append("model_requires_review")
    for name, item in proposed.fields.items():
        if item.value is None:
            output["fields"][name] = {"value": None, "evidence": None}
            continue
        quote = item.evidence or ""
        reason = None
        if not _evidence_in_document(quote, document.text):
            reason = "evidence_not_in_document"
        elif name == "company_inn":
            if not re.search(r"(?<!\d)" + re.escape(str(item.value)) + r"(?!\d)", quote):
                reason = "inn_not_supported_by_evidence"
        elif name in {"period_from", "period_to"}:
            if item.value not in _date_values(quote):
                reason = "date_not_supported_by_evidence"
        elif FIELD_KINDS[name] == "amount":
            if not _amount_in_quote(int(item.value), quote):
                reason = "amount_not_supported_by_evidence_or_units"
        if reason:
            output["issues"].append(f"{name}:{reason}")
            output["fields"][name] = {"value": None, "evidence": None}
        else:
            output["fields"][name] = {"value": item.value, "evidence": quote}

    inn = output["fields"]["company_inn"]["value"]
    if expected_inn and inn and inn != expected_inn:
        output["issues"].append("company_inn_mismatch")
    if expected_inn and not inn:
        output["issues"].append("company_inn_unconfirmed")
    a = output["fields"]["period_from"]["value"]
    b = output["fields"]["period_to"]["value"]
    if a is not None and b is not None and a > b:
        output["issues"].append("period_invalid")
    output["requires_review"] = bool(output["issues"])
    return output


def evaluate_cases(cases_path: str | Path, *, provider_name: str, base_url: str | None = None,
                   model: str | None = None, case_id: str | None = None) -> dict[str, Any]:
    """Evaluate evidence checks and field exact-match vs manually specified synthetic truth.

    No credentials, HTTP headers, or raw document text appear in this report.
    Mock accuracy is a test of code, NOT an estimate of real model accuracy.
    """
    manifest_path = Path(cases_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases file must contain nonempty cases list")
    if case_id is not None:
        cases = [case for case in cases if case.get("id") == case_id]
        if len(cases) != 1:
            raise ValueError("--case-id must name one existing case")
    if provider_name == "compatible":
        url = base_url or os.environ.get("DOCUMENT_LLM_BASE_URL")
        name = model or os.environ.get("DOCUMENT_LLM_MODEL")
        if not url or not name:
            raise ValueError("Set DOCUMENT_LLM_BASE_URL and DOCUMENT_LLM_MODEL")
        provider: FieldProvider = OpenAICompatibleProvider(base_url=url, model=name)
    elif provider_name == "mock":
        provider = StaticDemoProvider({c["id"]: c["mock_response"] for c in cases})
    else:
        raise ValueError("provider must be mock or compatible")

    records: list[dict[str, Any]] = []
    total_checked = 0
    exact_matches = 0
    correct_types = 0
    extraction_successes = 0
    non_null_expected = 0
    non_null_correct = 0
    for c in cases:
        file_path = (manifest_path.parent / c["filename"]).resolve()
        # The operator-supplied manifest is trusted; user-provided paths aren't.
        if not file_path.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError("Case file must remain within examples directory")
        text = extract_local_file(file_path)
        doc = UploadedDocument(c["id"], file_path.name, text)
        result = extract_verified_fields(doc, provider, expected_inn=c.get("expected_inn"))
        successful = "model_extraction_failed" not in result["issues"] and "no_readable_text_or_too_large" not in result["issues"]
        extraction_successes += int(successful)
        correct_types += int(successful and result["document_type"] == c.get("expected_type"))
        expected = c.get("expected_fields", {})
        field_accuracy = {}
        for name, truth in expected.items():
            if name not in FIELD_KINDS:
                raise ValueError(f"Unknown ground-truth field {name}")
            total_checked += 1
            actual = result["fields"].get(name, {}).get("value")
            matched = type(actual) is type(truth) and actual == truth
            field_accuracy[name] = matched
            exact_matches += int(matched)
            if truth is not None:
                non_null_expected += 1
                non_null_correct += int(matched)
        records.append({
            "document_id": c["id"], "filename": file_path.name,
            "extracted": result, "field_matches": field_accuracy,
            "correct_fields": sum(field_accuracy.values()), "evaluated_fields": len(field_accuracy),
            "document_type_correct": result["document_type"] == c.get("expected_type"),
            "expected_issues_found": successful and all(issue in result["issues"] for issue in c.get("expected_issues", [])),
        })
    return {
        "provider": provider_name,
        "cases": len(records),
        "field_exact_matches": exact_matches,
        "document_type_correct": correct_types,
        "field_evaluations": total_checked,
        "field_accuracy": (round(exact_matches / total_checked, 4) if total_checked else None) if extraction_successes else None,
        "field_accuracy_including_failures": round(exact_matches / total_checked, 4) if total_checked else None,
        "non_null_field_accuracy": round(non_null_correct / non_null_expected, 4) if non_null_expected else None,
        "non_null_correct": non_null_correct,
        "non_null_expected": non_null_expected,
        "successful_extractions": extraction_successes,
        "failed_extractions": len(cases) - extraction_successes,
        "records": records,
        "limitations": "Synthetic examples only; evidence checks cannot prove document authenticity or semantic correctness.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate LLM financial extraction on synthetic documents")
    ap.add_argument("--cases", default="ml/document_agent/examples/realistic/cases.json")
    ap.add_argument("--provider", choices=("mock", "compatible"), default="mock")
    ap.add_argument("--case-id", help="Optional: diagnose a single synthetic case before running all seven")
    ap.add_argument("--base-url")
    ap.add_argument("--model")
    ap.add_argument("--out", required=True, help="Path under ignored data/ is recommended")
    args = ap.parse_args()
    result = evaluate_cases(args.cases, provider_name=args.provider, base_url=args.base_url, model=args.model, case_id=args.case_id)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Cases={result['cases']}; successful extractions={result['successful_extractions']}; "
          f"non-null fields={result['non_null_correct']}/{result['non_null_expected']}; report={target}")
    if result["failed_extractions"]:
        print("WARNING: one or more extractions failed; inspect records[].extracted.diagnostic (no secrets included).")


if __name__ == "__main__":
    main()
