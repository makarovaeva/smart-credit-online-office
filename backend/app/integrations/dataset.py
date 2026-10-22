"""Запись о синтетическом заёмщике в формате генератора ML и загрузка датасета.

Формат задаёт ML. Лишние поля не отбрасываются (extra="allow"): если генератор начнёт отдавать
новые поля, они дойдут до признаков без правок здесь.
"""

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings


class _Block(BaseModel):
    model_config = ConfigDict(extra="allow")


class CompanyBlock(_Block):
    name: str
    # "OOO" | "IP"
    legal_form: str
    inn: str
    # ОГРН / ОГРНИП
    registration_number: str
    okved_main: str
    region_code: str
    registration_date: date
    employees_count: int


class FinancialsBlock(_Block):
    report_year: int
    revenue_rub: Decimal
    operating_costs_rub: Decimal
    ebitda_rub: Decimal
    cfads_rub: Decimal
    total_debt_rub: Decimal
    # Годовые платежи по действующим кредитам
    annual_debt_service_rub: Decimal
    assets_rub: Decimal
    liabilities_rub: Decimal
    equity_rub: Decimal


class FnsBlock(_Block):
    is_active: bool
    sme_category: str
    annual_income_rub: Decimal
    tax_debt_rub: Decimal


class BkiBlock(_Block):
    active_loans: int
    outstanding_debt_rub: Decimal
    overdue_debt_rub: Decimal
    max_overdue_days: int
    credit_history_months: int


class LoanApplicationBlock(_Block):
    requested_amount_rub: Decimal
    term_months: int
    purpose: str
    collateral_value_rub: Decimal | None = None


class BorrowerRecord(_Block):
    borrower_id: str
    application_id: str
    as_of_date: date
    company: CompanyBlock
    financials: FinancialsBlock
    fns: FnsBlock
    bki: BkiBlock
    loan_application: LoanApplicationBlock


def parse_dataset(text: str) -> list[BorrowerRecord]:
    """JSON Lines или JSON (одна запись или список)."""
    try:
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [BorrowerRecord.model_validate(row) for row in rows]


@lru_cache
def load_dataset(path: str) -> dict[str, BorrowerRecord]:
    """Записи по ИНН; если по ИНН несколько срезов - берётся самый свежий as_of_date."""
    records: dict[str, BorrowerRecord] = {}
    for record in parse_dataset(Path(path).read_text(encoding="utf-8")):
        current = records.get(record.company.inn)
        if current is None or record.as_of_date > current.as_of_date:
            records[record.company.inn] = record
    return records


def find_record(inn: str) -> BorrowerRecord | None:
    path = get_settings().borrower_dataset_path
    return load_dataset(path).get(inn) if path else None
