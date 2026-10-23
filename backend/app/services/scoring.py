"""Скоринг заёмщика: балл, Risk Grade A-E, уверенность модели и fraud-score.

Контракт ScoringModel: на входе плоские признаки Features.values, на выходе ScoringOutput.
Модель ML подключается реализацией ScoringModel и настройкой SCORING_MODEL; пока её нет,
работает прозрачная модель на правилах. Скоринг - вход для политики, а не кредитное решение.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from app.core.config import get_settings
from app.models.enums import RiskGrade

# Балл 300-900, как у кредитных бюро
MIN_SCORE, MAX_SCORE, BASE_SCORE = 300, 900, 700
GRADE_BANDS = ((800, RiskGrade.A), (720, RiskGrade.B), (650, RiskGrade.C), (580, RiskGrade.D))


@dataclass(frozen=True)
class ScoringFactor:
    code: str
    value: Any
    # Вклад в балл: + снижает риск, - повышает
    impact: int
    description: str


@dataclass(frozen=True)
class ScoringOutput:
    model_version: str
    score: int
    risk_grade: RiskGrade
    # 0..1; ниже 0,8 - эскалация аналитику
    confidence: Decimal
    # 0..1
    fraud_score: Decimal
    factors: list[ScoringFactor] = field(default_factory=list)


class ScoringModel(Protocol):
    async def score(self, features: Mapping[str, Any]) -> ScoringOutput: ...


def grade_for(score: int) -> RiskGrade:
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return RiskGrade.E


class RuleBasedScoring:
    """Объяснимая модель на правилах до появления модели ML."""

    version = "rules-1"

    async def score(self, features: Mapping[str, Any]) -> ScoringOutput:
        factors: list[ScoringFactor] = []

        def add(code: str, impact: int, description: str) -> None:
            factors.append(ScoringFactor(code, features.get(code), impact, description))

        if (dscr := features.get("dscr_existing")) is not None:
            if dscr >= 3:
                add("dscr_existing", 40, "EBITDA с запасом покрывает текущие платежи")
            elif dscr < 1.5:
                add("dscr_existing", -60, "EBITDA едва покрывает текущие платежи")
        if (leverage := features.get("debt_to_ebitda")) is not None and leverage > 3:
            add("debt_to_ebitda", -50, "Долг больше трёх EBITDA")
        if (margin := features.get("ebitda_margin")) is not None:
            if margin >= 0.2:
                add("ebitda_margin", 30, "Высокая рентабельность по EBITDA")
            elif margin < 0.05:
                add("ebitda_margin", -40, "Низкая рентабельность по EBITDA")
        if (age := features.get("business_age_months")) is not None:
            if age >= 60:
                add("business_age_months", 30, "Бизнесу больше 5 лет")
            elif age < 12:
                add("business_age_months", -60, "Бизнесу меньше года")
        if features.get("weak_credit_history"):
            add("weak_credit_history", -120, "Просрочки в кредитной истории")
        elif features.get("credit_history_quality") == "good":
            add("credit_history_quality", 30, "Хорошая кредитная история")
        if features.get("has_tax_debt"):
            add("has_tax_debt", -40, "Налоговая задолженность")
        if features.get("conflicting_data"):
            add("conflicting_data", -50, "Данные анкеты и источников расходятся")

        score = max(MIN_SCORE, min(MAX_SCORE, BASE_SCORE + sum(f.impact for f in factors)))
        return ScoringOutput(
            model_version=self.version,
            score=score,
            risk_grade=grade_for(score),
            confidence=self._confidence(features),
            fraud_score=self._fraud_score(features),
            factors=factors,
        )

    @staticmethod
    def _confidence(features: Mapping[str, Any]) -> Decimal:
        """Чем меньше данных и чем больше противоречий, тем ниже уверенность."""
        confidence = Decimal("0.92")
        for group in ("fin_annual_turnover", "bki_active_loans", "business_age_months"):
            if group not in features:
                confidence -= Decimal("0.15")
        if features.get("conflicting_data"):
            confidence -= Decimal("0.10")
        return max(Decimal("0"), confidence)

    @staticmethod
    def _fraud_score(features: Mapping[str, Any]) -> Decimal:
        signals = (
            features.get("employees_count") == 0,
            features.get("has_tax_activity") is False,
            bool(features.get("mass_address")),
            bool(features.get("mass_director")),
            bool(features.get("conflicting_data")),
        )
        return Decimal(sum(signals)) / len(signals)


_MODELS: dict[str, ScoringModel] = {"rules": RuleBasedScoring()}


def get_scoring_model() -> ScoringModel:
    return _MODELS[get_settings().scoring_model]
