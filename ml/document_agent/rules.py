"""Illustrative SME loan document checklist, not an actual bank policy."""
from __future__ import annotations

from .schema import DISPLAY_NAMES


def required_documents(application: dict, borrower: dict) -> list[str]:
    # These demo requirements intentionally live in one deterministic function.
    legal_form = borrower["company"]["legal_form"]
    base = ["registration_extract", "bank_statement"]
    if legal_form == "ooo":
        base.append("financial_statements")
    collateral = application.get("collateral") or {}
    if not isinstance(collateral, dict):
        raise ValueError("application.collateral must be object")
    if collateral.get("type", "none") in {"real_estate", "vehicle", "equipment"}:
        base.append("collateral_proof")
    return base


def customer_request(missing: list[str], manual_review: bool) -> str:
    if missing:
        names = "; ".join(DISPLAY_NAMES[t] for t in missing)
        message = f"Для продолжения рассмотрения загрузите: {names}."
    else:
        message = "Все документы из предварительного перечня представлены."
    if manual_review:
        message += " Некоторые сведения требуют проверки сотрудником."
    return message
