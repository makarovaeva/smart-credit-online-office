from decimal import Decimal

from app.models.enums import RiskGrade
from app.services.scoring import RuleBasedScoring, grade_for

HEALTHY = {
    "fin_annual_turnover": 60_000_000.0,
    "dscr_existing": 5.0,
    "debt_to_ebitda": 0.5,
    "ebitda_margin": 0.2,
    "business_age_months": 80,
    "bki_active_loans": 1,
    "credit_history_quality": "good",
    "weak_credit_history": False,
    "has_tax_debt": False,
    "conflicting_data": False,
    "employees_count": 20,
    "has_tax_activity": True,
}


def test_grade_bands() -> None:
    assert grade_for(850) == RiskGrade.A
    assert grade_for(720) == RiskGrade.B
    assert grade_for(650) == RiskGrade.C
    assert grade_for(580) == RiskGrade.D
    assert grade_for(579) == RiskGrade.E


async def test_healthy_borrower() -> None:
    result = await RuleBasedScoring().score(HEALTHY)
    assert result.risk_grade == RiskGrade.A
    assert result.confidence == Decimal("0.92")
    assert result.fraud_score == 0
    assert all(f.impact > 0 for f in result.factors)


async def test_risky_borrower_is_explained() -> None:
    risky = HEALTHY | {
        "dscr_existing": 1.2,
        "weak_credit_history": True,
        "has_tax_debt": True,
        "business_age_months": 8,
    }
    result = await RuleBasedScoring().score(risky)
    assert result.risk_grade == RiskGrade.E
    assert {f.code for f in result.factors} >= {
        "dscr_existing",
        "weak_credit_history",
        "has_tax_debt",
        "business_age_months",
    }


async def test_missing_data_and_conflicts_lower_confidence() -> None:
    no_bki = {k: v for k, v in HEALTHY.items() if not k.startswith("bki_")}
    assert (await RuleBasedScoring().score(no_bki)).confidence < Decimal("0.8")
    conflicting = HEALTHY | {"conflicting_data": True}
    result = await RuleBasedScoring().score(conflicting)
    assert result.confidence == Decimal("0.82")
    assert result.fraud_score > 0
