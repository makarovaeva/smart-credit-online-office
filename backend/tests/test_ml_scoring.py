from decimal import Decimal

import pytest

from app.models.enums import RiskGrade
from app.services import scoring
from app.services.scoring import MLServiceScoring, RuleBasedScoring, ScoringContext
from tests.test_scoring import HEALTHY

CONTEXT = ScoringContext(profile={"borrower_id": "brw_1"}, application={"application_id": "1"})
RESPONSE = {
    "model": "catboost",
    "calibration": "platt",
    "calibrated_probability": 0.05156543,
    "risk_increasing_factors": [
        {
            "feature": "legal_form",
            "name_ru": "Организационно-правовая форма",
            "impact_log_odds": 0.025,
        }
    ],
    "risk_reducing_factors": [
        {
            "feature": "ebitda_margin_pct",
            "name_ru": "Рентабельность EBITDA",
            "impact_log_odds": -0.063,
        }
    ],
}


def test_pd_mapping() -> None:
    assert scoring.grade_for_pd(Decimal("0.02")) == RiskGrade.A
    assert scoring.grade_for_pd(Decimal("0.05")) == RiskGrade.B
    assert scoring.grade_for_pd(Decimal("0.30")) == RiskGrade.E
    assert scoring.score_for_pd(Decimal("0")) == 900
    assert scoring.score_for_pd(Decimal("1")) == 300
    # Балл и грейд согласованы на всей шкале
    for pd in (Decimal(x) / 1000 for x in range(0, 1001, 5)):
        assert scoring.grade_for(scoring.score_for_pd(pd)) == scoring.grade_for_pd(pd), pd


async def test_ml_response_is_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    model = MLServiceScoring(RuleBasedScoring())
    monkeypatch.setattr(model, "_post", lambda payload: RESPONSE)
    result = await model.score(HEALTHY, CONTEXT)

    assert result.model_version == "ml-catboost-platt"
    assert result.risk_grade == RiskGrade.B
    assert result.score == 742
    # Уверенность и fraud-score - по данным, как у правил
    assert result.confidence == Decimal("0.92")
    assert [(f.code, f.impact) for f in result.factors] == [
        ("legal_form", -2),
        ("ebitda_margin_pct", 6),
    ]


async def test_falls_back_to_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    model = MLServiceScoring(RuleBasedScoring())

    def unavailable(payload):
        raise OSError("connection refused")

    monkeypatch.setattr(model, "_post", unavailable)
    rules = await RuleBasedScoring().score(HEALTHY)
    result = await model.score(HEALTHY, CONTEXT)
    assert result.model_version == "rules-1 (ML недоступен)"
    assert (result.score, result.risk_grade) == (rules.score, rules.risk_grade)

    no_data = await model.score(HEALTHY, ScoringContext())
    assert no_data.model_version == "rules-1 (нет данных для ML)"
