from datetime import date
from decimal import Decimal

import pytest

from app.integrations import SOURCES, CompanyNotFoundError, SourceUnavailableError, bki, egrul
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


async def fetch_all(inn: str) -> dict[CheckSource, dict]:
    results = {}
    for source, fetch in SOURCES.items():
        try:
            results[source] = await fetch(inn, TODAY)
        except SourceUnavailableError:
            pass
    return results


async def test_same_inn_gives_same_data() -> None:
    for source, fetch in SOURCES.items():
        assert await fetch("7712345678", TODAY) == await fetch("7712345678", TODAY), source


async def test_legal_form_by_inn_length() -> None:
    assert (await egrul.fetch("7712345678", TODAY))["legal_form"] == "ooo"
    ip = await egrul.fetch("771234567890", TODAY)
    assert ip["legal_form"] == "ip"
    assert ip["name"].startswith("ИП ")
    assert ip["kpp"] is None


async def test_sources_are_consistent() -> None:
    results = await fetch_all(HEALTHY)
    revenue = Decimal(results[CheckSource.FNS]["revenue"])
    inflow = sum(Decimal(m["inflow"]) for m in results[CheckSource.BANK_TURNOVER]["months"])
    assert abs(inflow - revenue) / revenue < Decimal("0.05")
    assert len(results[CheckSource.BANK_TURNOVER]["months"]) == 12
    assert results[CheckSource.BANK_TURNOVER]["months"][-1]["month"] == "2026-09"


async def test_unavailable_and_unknown_company() -> None:
    with pytest.raises(SourceUnavailableError):
        await bki.fetch("7701000011", TODAY)
    with pytest.raises(CompanyNotFoundError):
        await egrul.fetch("7701000099", TODAY)


@pytest.mark.parametrize(
    ("inn", "flags"),
    [
        ("7701000002", {StopFactorCode.BANKRUPTCY}),
        ("7701000003", {StopFactorCode.ACCOUNTS_BLOCKED_115FZ}),
        ("7701000004", {StopFactorCode.SANCTIONED_OWNER}),
        ("7701000005", {StopFactorCode.MASS_ADDRESS, StopFactorCode.MASS_DIRECTOR}),
        ("7701000006", {StopFactorCode.NO_EMPLOYEES, StopFactorCode.NO_TAX_ACTIVITY}),
        ("7701000012", {StopFactorCode.PROHIBITED_ACTIVITY}),
    ],
)
async def test_stop_factor_scenarios(inn: str, flags: set[StopFactorCode]) -> None:
    features = build_features(await fetch_all(inn), today=TODAY)
    assert features.signals.flags == flags


async def test_healthy_company_has_no_signals() -> None:
    features = build_features(await fetch_all(HEALTHY), today=TODAY)
    s = features.signals
    assert s.flags == frozenset()
    assert not s.weak_credit_history
    assert not s.conflicting_data
    assert s.negative_cash_flow_months == 0
    assert s.revenue_drop < Decimal("0.1")
    assert s.business_age_months >= 12
    assert features.missing_sources == []
    assert features.existing_annual_debt_service > 0


async def test_signal_scenarios() -> None:
    assert (
        build_features(await fetch_all("7701000007"), today=TODAY).signals.negative_cash_flow_months
        == 4
    )
    assert (
        build_features(await fetch_all("7701000008"), today=TODAY).signals.business_age_months == 7
    )
    assert build_features(await fetch_all("7701000009"), today=TODAY).signals.weak_credit_history
    drop = build_features(await fetch_all("7701000010"), today=TODAY).signals.revenue_drop
    assert Decimal("0.2") <= drop <= Decimal("0.3")


async def test_missing_source_is_reported_not_guessed() -> None:
    features = build_features(await fetch_all("7701000011"), today=TODAY)
    assert features.missing_sources == [CheckSource.BKI]
    assert features.existing_annual_debt_service is None
    assert "bki_score" not in features.values


async def test_fssp_and_tax_debt() -> None:
    values = build_features(await fetch_all("7701000014"), today=TODAY).values
    assert values["fssp_open_proceedings"] == 2
    assert values["fssp_total_amount"] == 890000.0
    assert values["fns_tax_debt"] == 320000.0


async def test_declared_data_conflicts_with_sources() -> None:
    results = await fetch_all(HEALTHY)
    revenue = Decimal(results[CheckSource.FNS]["revenue"])
    features = build_features(results, declared_revenue=revenue * 2, today=TODAY)
    assert features.signals.conflicting_data
    assert features.conflicts == ["Выручка в анкете расходится с отчётностью в ФНС"]
    assert not build_features(results, declared_revenue=revenue, today=TODAY).conflicts


async def test_ml_features_are_flat() -> None:
    values = build_features(await fetch_all(HEALTHY), today=TODAY).values
    assert all(isinstance(v, int | float | str | bool) for v in values.values())


def policy_input(inn_features, amount: str = "3000000") -> PolicyInput:
    revenue = Decimal(str(inn_features.values["fns_revenue"]))
    return PolicyInput(
        amount=Decimal(amount),
        term_months=36,
        base_rate=Decimal("18"),
        min_amount=Decimal("300000"),
        max_term_months=60,
        annual_revenue=revenue,
        ebitda=revenue * Decimal("0.15"),
        existing_annual_debt_service=inn_features.existing_annual_debt_service,
        signals=inn_features.signals,
    )


async def test_features_drive_credit_policy() -> None:
    healthy = build_features(await fetch_all(HEALTHY), today=TODAY)
    result = evaluate(policy_input(healthy))
    assert result.zone == RiskZone.GREEN
    assert result.recommendation == AiRecommendation.APPROVE

    bankrupt = build_features(await fetch_all("7701000002"), today=TODAY)
    assert evaluate(policy_input(bankrupt)).zone == RiskZone.RED

    young = build_features(await fetch_all("7701000008"), today=TODAY)
    assert evaluate(policy_input(young)).escalation_reasons == [EscalationReasonCode.YOUNG_BUSINESS]
