"""Профиль заёмщика (Borrower Profile) из docs/credit_mmb_data_model_updated.md и загрузка датасета.

Формат согласован командой и генератором ML. Обязательны поля, по которым принимаются решения
(компания, fns_data, compliance, bki_data, financials). Блоки для экранов (head, owners, contacts,
bank_account, documents) необязательны. Лишние поля не отбрасываются (extra="allow"): например,
балансовые показатели ML в financials сами становятся признаками.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings


class _Block(BaseModel):
    model_config = ConfigDict(extra="allow")


class Okved(_Block):
    code: str
    name: str | None = None


class CompanyBlock(_Block):
    legal_form: str
    full_name: str
    short_name: str
    inn: str
    kpp: str | None = None
    ogrn: str
    registration_date: date
    legal_address: str | None = None
    actual_address: str | None = None
    okved_main: Okved
    tax_system: str | None = None
    employees_count: int
    region_code: str


class HeadBlock(_Block):
    full_name: str
    position: str | None = None
    inn_individual: str | None = None
    birth_date: date | None = None
    in_position_since: date | None = None
    has_signing_authority: bool | None = None


class OwnerBlock(_Block):
    owner_id: str | None = None
    owner_type: str | None = None
    name: str
    inn: str | None = None
    ownership_share_pct: Decimal | None = None
    is_beneficiary: bool = True
    has_signing_authority: bool | None = None


class FnsDataBlock(_Block):
    retrieved_at: datetime | None = None
    egrul_status: Literal["active", "liquidating", "liquidated"]
    bankruptcy_status: Literal["none", "observation", "bankruptcy"]
    has_account_block_115fz: bool
    is_mass_address: bool
    is_mass_director: bool
    has_tax_activity: bool
    tax_arrears_amount: Decimal


class ComplianceBlock(_Block):
    checked_at: datetime | None = None
    source: str | None = None
    sanctions_hit: bool
    is_prohibited_activity: bool


class BkiDataBlock(_Block):
    retrieved_at: datetime | None = None
    bureau: str | None = None
    credit_history_quality: Literal["good", "weak", "none"]
    active_loans_count: int
    total_debt_amount: Decimal
    monthly_debt_service: Decimal
    overdue_amount: Decimal
    max_overdue_days_12m: int


class FinancialsBlock(_Block):
    as_of_date: date | None = None
    annual_turnover: Decimal
    revenue_change_pct: Decimal
    ebitda: Decimal
    cash_flow_period_end: str | None = None
    # Чистый денежный поток по месяцам, от старого к новому
    cash_flow_last_12m: list[Decimal] = Field(min_length=1, max_length=12)
    source: str | None = None


class BorrowerProfile(_Block):
    borrower_id: str
    status: str = "active"
    customer_since: date | None = None
    company: CompanyBlock
    head: HeadBlock | None = None
    owners: list[OwnerBlock] = []
    contacts: dict | None = None
    fns_data: FnsDataBlock
    compliance: ComplianceBlock
    bki_data: BkiDataBlock
    financials: FinancialsBlock
    bank_account: dict | None = None
    documents: list[dict] = []


def parse_dataset(text: str) -> list[BorrowerProfile]:
    """JSON Lines или JSON (один профиль или список)."""
    try:
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [BorrowerProfile.model_validate(row) for row in rows]


@lru_cache
def load_dataset(path: str) -> dict[str, BorrowerProfile]:
    """Профили по ИНН; если по ИНН несколько, берётся последний в файле."""
    return {
        profile.company.inn: profile
        for profile in parse_dataset(Path(path).read_text(encoding="utf-8"))
    }


def find_profile(inn: str) -> BorrowerProfile | None:
    path = get_settings().borrower_dataset_path
    return load_dataset(path).get(inn) if path else None
