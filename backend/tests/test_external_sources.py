import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.integrations import SOURCES, CompanyNotFoundError, SourceUnavailableError, bki, egrul
from app.integrations.dataset import parse_dataset
from app.models.enums import (
    AiRecommendation,
    CheckSource,
    EscalationReasonCode,
    RiskZone,
    StopFactorCode,
)
from app.services.credit_policy import PolicyInput, evaluate
from app.services.features import build_features

TODAY = date(2026, 10, 21)
HEALTHY = "7701000001"
ML_EXAMPLE = Path(__file__).parent / "fixtures" / "ml_borrower_example.json"


async def fetch_all(inn: str) -> dict[CheckSource, dict]:
    results = {}
    for source, fetch in SOURCES.items():
        try:
            results[source] = await fetch(inn, TODAY)
        except SourceUnavailableError:
            pass
    return results


def features_of(results: dict, **kwargs):
    return build_features(results, today=TODAY, **kwargs)


@pytest.fixture
def ml_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Датасет из одной записи - ровно в том виде, как её прислал ML."""
    record = json.loads(ML_EXAMPLE.read_text())
    dataset = tmp_path / "borrowers.jsonl"
    dataset.write_text(json.dumps(record, ensure_ascii=False) + "\n")
    monkeypatch.setattr(get_settings(), "borrower_dataset_path", str(dataset))
    return record


def policy_input(features, amount: str = "3000000") -> PolicyInput:
    v = features.values
    return PolicyInput(
        amount=Decimal(amount),
        term_months=36,
        base_rate=Decimal("18"),
        min_amount=Decimal("300000"),
        max_term_months=60,
        annual_revenue=Decimal(str(v["fin_revenue"])),
        ebitda=Decimal(str(v["fin_ebitda"])),
        existing_annual_debt_service=features.existing_annual_debt_service,
        signals=features.signals,
    )


# --- Формат ML ---


def test_ml_example_is_accepted_as_is() -> None:
    [record] = parse_dataset(ML_EXAMPLE.read_text())
    assert record.company.inn == "7700000000"
    assert record.financials.ebitda_rub == 4000000


def test_dataset_formats_and_extra_fields() -> None:
    row = json.loads(ML_EXAMPLE.read_text())
    row["fns"]["blocked_115fz"] = True
    jsonl = "\n".join(json.dumps(r) for r in (row, row))
    assert len(parse_dataset(jsonl)) == 2
    assert len(parse_dataset(json.dumps([row, row], indent=2))) == 2
    assert parse_dataset(json.dumps(row))[0].fns.model_extra == {"blocked_115fz": True}


def test_dataset_rejects_wrong_format() -> None:
    row = json.loads(ML_EXAMPLE.read_text())
    del row["bki"]["max_overdue_days"]
    with pytest.raises(ValueError, match="max_overdue_days"):
        parse_dataset(json.dumps(row))


async def test_mocks_serve_ml_record(ml_dataset: dict) -> None:
    results = await fetch_all("7700000000")
    assert results[CheckSource.EGRUL]["registration_number"] == "1027700000000"
    assert results[CheckSource.FNS]["financials"]["ebitda_rub"] == "4000000"
    assert results[CheckSource.BKI]["credit_history_months"] == 48

    features = features_of(results, declared_revenue=Decimal("25000000"))
    assert features.signals.flags == frozenset()
    assert features.signals.business_age_months == 77
    assert features.existing_annual_debt_service == Decimal("1500000")
    assert features.values["debt_to_ebitda"] == 1.25
    assert features.values["legal_form"] == "ooo"
    assert features.conflicts == []

    result = evaluate(policy_input(features))
    assert result.zone == RiskZone.GREEN


async def test_record_extensions_enable_signals(
    ml_dataset: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Поля сверх базового формата ML включают дополнительные стоп-факторы."""
    ml_dataset["fns"] |= {"blocked_115fz": True, "mass_address": True}
    ml_dataset["company"]["founders"] = [{"full_name": "Иванов И. И.", "sanctions_match": True}]
    dataset = tmp_path / "extended.jsonl"
    dataset.write_text(json.dumps(ml_dataset, ensure_ascii=False))
    monkeypatch.setattr(get_settings(), "borrower_dataset_path", str(dataset))

    flags = features_of(await fetch_all("7700000000")).signals.flags
    assert flags == {
        StopFactorCode.ACCOUNTS_BLOCKED_115FZ,
        StopFactorCode.MASS_ADDRESS,
        StopFactorCode.SANCTIONED_OWNER,
    }


# --- Запасной генератор ---


async def test_same_inn_gives_same_data() -> None:
    for source, fetch in SOURCES.items():
        assert await fetch("7712345678", TODAY) == await fetch("7712345678", TODAY), source


async def test_legal_form_by_inn_length() -> None:
    assert (await egrul.fetch("7712345678", TODAY))["legal_form"] == "OOO"
    ip = await egrul.fetch("771234567890", TODAY)
    assert ip["legal_form"] == "IP"
    assert ip["name"].startswith("ИП ")


async def test_unavailable_and_unknown_company() -> None:
    with pytest.raises(SourceUnavailableError):
        await bki.fetch("7701000011", TODAY)
    with pytest.raises(CompanyNotFoundError):
        await egrul.fetch("7701000099", TODAY)


@pytest.mark.parametrize(
    ("inn", "flags"),
    [
        ("7701000002", {StopFactorCode.BANKRUPTCY}),
        ("7701000003", {StopFactorCode.PROHIBITED_ACTIVITY}),
        ("7701000004", {StopFactorCode.NO_EMPLOYEES}),
        ("7701000005", {StopFactorCode.NO_TAX_ACTIVITY}),
    ],
)
async def test_stop_factor_scenarios(inn: str, flags: set[StopFactorCode]) -> None:
    assert features_of(await fetch_all(inn)).signals.flags == flags


async def test_healthy_company() -> None:
    features = features_of(await fetch_all(HEALTHY))
    s = features.signals
    assert s.flags == frozenset()
    assert not s.weak_credit_history
    assert not s.conflicting_data
    assert s.business_age_months >= 12
    assert features.missing_sources == []
    assert features.existing_annual_debt_service > 0
    assert all(isinstance(v, int | float | str | bool) for v in features.values.values())


async def test_scenarios_through_credit_policy() -> None:
    healthy = evaluate(policy_input(features_of(await fetch_all(HEALTHY))))
    assert healthy.zone == RiskZone.GREEN
    assert healthy.recommendation == AiRecommendation.APPROVE

    low_dscr = evaluate(policy_input(features_of(await fetch_all("7701000006"))))
    assert low_dscr.stop_factors == [StopFactorCode.LOW_DSCR]

    young = evaluate(policy_input(features_of(await fetch_all("7701000007"))))
    assert young.escalation_reasons == [EscalationReasonCode.YOUNG_BUSINESS]

    weak = evaluate(policy_input(features_of(await fetch_all("7701000008"))))
    assert EscalationReasonCode.WEAK_CREDIT_HISTORY in weak.escalation_reasons

    conflict = evaluate(policy_input(features_of(await fetch_all("7701000009"))))
    assert EscalationReasonCode.CONFLICTING_DATA in conflict.escalation_reasons

    heavy = evaluate(policy_input(features_of(await fetch_all("7701000010"))))
    assert EscalationReasonCode.NO_COUNTER_OFFER in heavy.escalation_reasons


async def test_missing_source_is_reported_not_guessed() -> None:
    features = features_of(await fetch_all("7701000011"))
    assert features.missing_sources == [CheckSource.BKI]
    assert "weak_credit_history" not in features.values


async def test_tax_debt_and_declared_data_conflict() -> None:
    results = await fetch_all("7701000012")
    assert features_of(results).values["has_tax_debt"]

    income = Decimal(results[CheckSource.FNS]["annual_income_rub"])
    features = features_of(results, declared_revenue=income * 2)
    assert features.conflicts == ["Выручка в анкете расходится с данными ФНС"]
