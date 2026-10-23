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

SC = StopFactorCode
TODAY = date(2026, 10, 23)
HEALTHY = "7701000001"
EXAMPLE = Path(__file__).parent / "fixtures" / "borrower_profile_example.json"


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


def use_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *profiles: dict) -> None:
    dataset = tmp_path / "borrowers.jsonl"
    dataset.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in profiles))
    monkeypatch.setattr(get_settings(), "borrower_dataset_path", str(dataset))


def policy_input(features, amount: str = "3000000") -> PolicyInput:
    v = features.values
    return PolicyInput(
        amount=Decimal(amount),
        term_months=36,
        base_rate=Decimal("18"),
        min_amount=Decimal("300000"),
        max_term_months=60,
        annual_revenue=Decimal(str(v["fin_annual_turnover"])),
        ebitda=Decimal(str(v["fin_ebitda"])),
        existing_annual_debt_service=features.existing_annual_debt_service or Decimal(0),
        signals=features.signals,
    )


# --- Формат профиля из docs/credit_mmb_data_model_updated.md ---


def test_document_example_is_accepted_as_is() -> None:
    [profile] = parse_dataset(EXAMPLE.read_text())
    assert profile.company.short_name == "ООО «Вектор»"
    assert len(profile.financials.cash_flow_last_12m) == 12


def test_dataset_formats_extra_fields_and_errors() -> None:
    row = json.loads(EXAMPLE.read_text())
    row["financials"]["equity"] = 10_000_000
    assert len(parse_dataset("\n".join(json.dumps(r) for r in (row, row)))) == 2
    assert len(parse_dataset(json.dumps([row, row], indent=2))) == 2
    assert parse_dataset(json.dumps(row))[0].financials.model_extra == {"equity": 10_000_000}

    del row["fns_data"]["has_account_block_115fz"]
    with pytest.raises(ValueError, match="has_account_block_115fz"):
        parse_dataset(json.dumps(row))


async def test_mocks_serve_dataset_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = json.loads(EXAMPLE.read_text())
    # Поле генератора ML сверх формата документа становится признаком
    profile["financials"]["equity"] = 10_000_000
    use_dataset(tmp_path, monkeypatch, profile)

    results = await fetch_all("7701234567")
    assert results[CheckSource.EGRUL]["company"]["ogrn"] == "1157746123456"
    assert results[CheckSource.FNS]["financials"]["ebitda"] == "5000000"
    assert results[CheckSource.BKI]["bki_data"]["monthly_debt_service"] == "40000"
    assert results[CheckSource.COMPLIANCE]["compliance"]["sanctions_hit"] is False

    features = features_of(results, declared_revenue=Decimal("18000000"))
    s = features.signals
    assert s.flags == frozenset()
    assert s.business_age_months == 66
    assert s.negative_cash_flow_months == 0
    assert s.revenue_drop == Decimal("0.042")
    assert not s.weak_credit_history
    assert features.existing_annual_debt_service == Decimal("480000")
    assert features.values["fin_equity"] == 10_000_000.0
    assert features.values["dscr_existing"] == pytest.approx(10.4167)
    assert features.conflicts == []
    assert evaluate(policy_input(features)).zone == RiskZone.GREEN


async def test_all_stop_factors_come_from_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = json.loads(EXAMPLE.read_text())
    profile["fns_data"] |= {
        "bankruptcy_status": "bankruptcy",
        "has_account_block_115fz": True,
        "is_mass_address": True,
        "is_mass_director": True,
        "has_tax_activity": False,
    }
    profile["compliance"] |= {"sanctions_hit": True, "is_prohibited_activity": True}
    profile["financials"]["cash_flow_last_12m"][-4:] = [-1, -1, -1, -1]
    profile["company"]["employees_count"] = 0
    use_dataset(tmp_path, monkeypatch, profile)

    features = features_of(await fetch_all("7701234567"))
    assert features.signals.flags == {
        SC.BANKRUPTCY,
        SC.ACCOUNTS_BLOCKED_115FZ,
        SC.MASS_ADDRESS,
        SC.MASS_DIRECTOR,
        SC.NO_TAX_ACTIVITY,
        SC.SANCTIONED_OWNER,
        SC.PROHIBITED_ACTIVITY,
        SC.NO_EMPLOYEES,
    }
    result = evaluate(policy_input(features))
    assert SC.NEGATIVE_CASH_FLOW in result.stop_factors


# --- Запасной генератор и демо-ИНН ---


async def test_same_inn_gives_same_data() -> None:
    for source, fetch in SOURCES.items():
        assert await fetch("7712345678", TODAY) == await fetch("7712345678", TODAY), source


async def test_legal_form_by_inn_length() -> None:
    assert (await egrul.fetch("7712345678", TODAY))["company"]["legal_form"] == "ooo"
    ip = (await egrul.fetch("771234567890", TODAY))["company"]
    assert ip["legal_form"] == "ip"
    assert ip["short_name"].startswith("ИП ")
    assert ip["kpp"] is None


async def test_unavailable_and_unknown_company() -> None:
    with pytest.raises(SourceUnavailableError):
        await bki.fetch("7701000011", TODAY)
    with pytest.raises(CompanyNotFoundError):
        await egrul.fetch("7701000099", TODAY)


@pytest.mark.parametrize(
    ("inn", "stop_factors"),
    [
        ("7701000002", [SC.BANKRUPTCY]),
        ("7701000003", [SC.PROHIBITED_ACTIVITY]),
        ("7701000004", [SC.NO_EMPLOYEES]),
        ("7701000005", [SC.NO_TAX_ACTIVITY]),
        ("7701000006", [SC.LOW_DSCR]),
        ("7701000009", [SC.ACCOUNTS_BLOCKED_115FZ]),
        ("7701000013", [SC.SANCTIONED_OWNER]),
        ("7701000014", [SC.MASS_ADDRESS, SC.MASS_DIRECTOR]),
        ("7701000015", [SC.NEGATIVE_CASH_FLOW]),
        ("7701000017", [SC.OBSERVATION_PROCEDURE]),
    ],
)
async def test_stop_factor_scenarios(inn: str, stop_factors: list[StopFactorCode]) -> None:
    result = evaluate(policy_input(features_of(await fetch_all(inn))))
    assert result.zone == RiskZone.RED
    assert result.stop_factors == stop_factors


async def test_healthy_company() -> None:
    features = features_of(await fetch_all(HEALTHY))
    assert features.signals.flags == frozenset()
    assert features.missing_sources == []
    assert features.existing_annual_debt_service > 0
    assert all(isinstance(v, int | float | str | bool) for v in features.values.values())
    result = evaluate(policy_input(features))
    assert result.zone == RiskZone.GREEN
    assert result.recommendation == AiRecommendation.APPROVE


async def test_escalation_and_premium_scenarios() -> None:
    young = evaluate(policy_input(features_of(await fetch_all("7701000007"))))
    assert young.escalation_reasons == [EscalationReasonCode.YOUNG_BUSINESS]

    weak = evaluate(policy_input(features_of(await fetch_all("7701000008"))))
    assert EscalationReasonCode.WEAK_CREDIT_HISTORY in weak.escalation_reasons

    drop = evaluate(policy_input(features_of(await fetch_all("7701000016"))))
    assert drop.zone == RiskZone.GREEN
    assert [a.scenario for a in drop.adjustments] == ["risk_premium"]

    borderline = evaluate(policy_input(features_of(await fetch_all("7701000018")), "5000000"))
    assert borderline.recommendation == AiRecommendation.COUNTER_OFFER
    assert any(o.terms.amount == Decimal("5000000") for o in borderline.alternatives)


async def test_missing_source_is_reported_not_guessed() -> None:
    features = features_of(await fetch_all("7701000011"))
    assert features.missing_sources == [CheckSource.BKI]
    assert features.existing_annual_debt_service is None
    assert "weak_credit_history" not in features.values


async def test_tax_debt_and_declared_data_conflict() -> None:
    results = await fetch_all("7701000012")
    assert features_of(results).values["has_tax_debt"]

    turnover = Decimal(results[CheckSource.FNS]["financials"]["annual_turnover"])
    features = features_of(results, declared_revenue=turnover * 2)
    assert features.conflicts == ["Выручка в анкете расходится с данными отчётности"]
