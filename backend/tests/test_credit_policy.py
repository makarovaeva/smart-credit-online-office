from dataclasses import replace
from decimal import Decimal

from app.models.enums import (
    AiRecommendation,
    AlternativeOfferKind,
    CollateralType,
    CounterOfferScenario,
    EscalationReasonCode,
    RiskZone,
    StopFactorCode,
)
from app.services.credit_policy import DEFAULT_THRESHOLDS, PolicyInput, RiskSignals, evaluate

Scenario = CounterOfferScenario
D = Decimal

# Зелёная зона: DSCR ~3.2, Debt Burden ~32%, без залога
GREEN = PolicyInput(
    amount=D("3000000"),
    term_months=36,
    base_rate=D("18"),
    min_amount=D("300000"),
    max_term_months=60,
    annual_revenue=D("30000000"),
    ebitda=D("6000000"),
    existing_annual_debt_service=D("600000"),
)


def scenarios(result) -> list[CounterOfferScenario]:
    return [a.scenario for a in result.adjustments]


def assert_green_terms(result) -> None:
    m = result.recommended_metrics
    assert m.dscr >= DEFAULT_THRESHOLDS.min_dscr
    assert m.debt_burden <= DEFAULT_THRESHOLDS.max_debt_burden
    assert m.ltv is None or m.ltv <= DEFAULT_THRESHOLDS.max_ltv


def test_green_zone_gets_requested_terms() -> None:
    result = evaluate(GREEN)
    assert result.zone == RiskZone.GREEN
    assert result.recommendation == AiRecommendation.APPROVE
    assert result.adjustments == []
    assert result.recommended_terms.amount == GREEN.amount


def test_stop_factor_is_auto_decline() -> None:
    result = evaluate(
        replace(GREEN, signals=RiskSignals(flags=frozenset({StopFactorCode.MASS_DIRECTOR})))
    )
    assert result.zone == RiskZone.RED
    assert result.recommendation == AiRecommendation.DECLINE
    assert result.stop_factors == [StopFactorCode.MASS_DIRECTOR]
    assert result.recommended_terms is None


def test_financial_stop_factors() -> None:
    result = evaluate(
        replace(GREEN, ebitda=D("1500000"), signals=RiskSignals(negative_cash_flow_months=4))
    )
    assert result.stop_factors == [StopFactorCode.NEGATIVE_CASH_FLOW, StopFactorCode.LOW_DSCR]


def test_auto_approval_limit_is_lesser_of_5m_and_20_percent_revenue() -> None:
    result = evaluate(replace(GREEN, amount=D("8000000"), ebitda=D("20000000")))
    assert scenarios(result) == [Scenario.AUTO_APPROVAL_LIMIT]
    assert result.recommended_terms.amount == D("5000000")
    assert result.zone == RiskZone.GREEN
    assert result.recommendation == AiRecommendation.COUNTER_OFFER

    small_business = evaluate(replace(GREEN, annual_revenue=D("10000000")))
    assert small_business.recommended_terms.amount == D("2000000")


def test_low_dscr_extends_term() -> None:
    result = evaluate(replace(GREEN, ebitda=D("2000000")))
    assert result.requested_metrics.dscr < DEFAULT_THRESHOLDS.min_dscr
    # Debt Burden = 1 / DSCR, поэтому одного продления срока до <50% не хватает
    assert scenarios(result) == [Scenario.TERM_EXTENSION, Scenario.DEBT_BURDEN_AMOUNT_REDUCTION]
    assert GREEN.term_months < result.recommended_terms.term_months <= GREEN.max_term_months
    assert result.zone == RiskZone.GREEN
    assert_green_terms(result)


def test_high_debt_burden_reduces_amount() -> None:
    result = evaluate(replace(GREEN, ebitda=D("3500000")))
    assert scenarios(result) == [Scenario.DEBT_BURDEN_AMOUNT_REDUCTION]
    assert result.recommended_terms.amount < GREEN.amount
    assert result.recommended_terms.amount % 1000 == 0
    assert_green_terms(result)


def test_high_ltv_reduces_amount_and_escalates() -> None:
    result = evaluate(
        replace(
            GREEN,
            collateral_type=CollateralType.COMMERCIAL_REAL_ESTATE,
            collateral_market_value=D("4000000"),
        )
    )
    assert scenarios(result) == [Scenario.LTV_AMOUNT_REDUCTION]
    # 4 млн * (1 - 0.3) * 70%
    assert result.recommended_terms.amount == D("1960000")
    assert result.zone == RiskZone.YELLOW
    assert result.escalation_reasons == [EscalationReasonCode.HIGH_LTV]
    assert_green_terms(result)


def test_revenue_drop_adds_risk_premium() -> None:
    result = evaluate(replace(GREEN, signals=RiskSignals(revenue_drop=D("0.25"))))
    assert scenarios(result) == [Scenario.RISK_PREMIUM]
    assert result.recommended_terms.rate == D("20")
    assert result.recommended_terms.amount == GREEN.amount
    assert result.zone == RiskZone.GREEN


def test_weak_credit_history_goes_to_analyst_with_premium() -> None:
    result = evaluate(replace(GREEN, signals=RiskSignals(weak_credit_history=True)))
    assert scenarios(result) == [Scenario.RISK_PREMIUM]
    assert result.zone == RiskZone.YELLOW
    assert result.escalation_reasons == [EscalationReasonCode.WEAK_CREDIT_HISTORY]


def test_escalation_is_not_decline() -> None:
    signals = RiskSignals(model_confidence=D("0.7"), business_age_months=6, conflicting_data=True)
    result = evaluate(replace(GREEN, signals=signals))
    assert result.zone == RiskZone.YELLOW
    assert result.recommendation == AiRecommendation.APPROVE
    assert result.escalation_reasons == [
        EscalationReasonCode.LOW_CONFIDENCE,
        EscalationReasonCode.YOUNG_BUSINESS,
        EscalationReasonCode.CONFLICTING_DATA,
    ]


def test_unfixable_debt_burden_escalates() -> None:
    # Действующие платежи уже съедают больше 50% EBITDA
    result = evaluate(replace(GREEN, existing_annual_debt_service=D("3500000")))
    assert result.stop_factors == []
    assert result.zone == RiskZone.YELLOW
    assert EscalationReasonCode.NO_COUNTER_OFFER in result.escalation_reasons


# --- Альтернативные варианты ---

Kind = AlternativeOfferKind


def kinds(result) -> list[AlternativeOfferKind]:
    return [o.kind for o in result.alternatives]


def test_no_alternatives_when_requested_terms_pass() -> None:
    assert evaluate(GREEN).alternatives == []


def test_longer_term_keeps_requested_amount() -> None:
    result = evaluate(replace(GREEN, ebitda=D("3500000")))
    # Последовательные сценарии политики режут сумму...
    assert result.recommended_terms.amount < GREEN.amount
    # ...а вариант «дольше срок» сохраняет её целиком
    assert kinds(result) == [Kind.LONGER_TERM, Kind.LOWER_AMOUNT, Kind.MAX_TERM]
    longer, lower, max_term = result.alternatives
    assert longer.terms.amount == GREEN.amount
    assert GREEN.term_months < longer.terms.term_months < GREEN.max_term_months
    assert lower.terms.term_months == GREEN.term_months
    assert max_term.terms.term_months == GREEN.max_term_months
    for offer in result.alternatives:
        assert offer.metrics.dscr >= DEFAULT_THRESHOLDS.min_dscr
        assert offer.metrics.debt_burden <= DEFAULT_THRESHOLDS.max_debt_burden
        assert offer.terms.amount % 1000 == 0
        assert "мес." in offer.description


def test_longest_term_gives_more_than_sequential_scenarios() -> None:
    result = evaluate(replace(GREEN, ebitda=D("2000000")))
    # Даже на максимальном сроке всю сумму не сохранить
    assert kinds(result) == [Kind.LOWER_AMOUNT, Kind.MAX_TERM]
    assert result.alternatives[1].terms.amount > result.recommended_terms.amount


def test_alternatives_respect_hard_caps_and_premium() -> None:
    ltv = evaluate(
        replace(
            GREEN,
            collateral_type=CollateralType.COMMERCIAL_REAL_ESTATE,
            collateral_market_value=D("4000000"),
        )
    )
    assert all(o.terms.amount <= D("1960000") for o in ltv.alternatives)
    assert Kind.LONGER_TERM not in kinds(ltv)

    premium = evaluate(
        replace(GREEN, ebitda=D("3500000"), signals=RiskSignals(revenue_drop=D("0.25")))
    )
    assert {o.terms.rate for o in premium.alternatives} == {D("20")}


def test_no_alternatives_when_nothing_fits() -> None:
    assert evaluate(replace(GREEN, existing_annual_debt_service=D("3500000"))).alternatives == []
