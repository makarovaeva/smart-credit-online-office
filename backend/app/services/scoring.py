"""Скоринг заёмщика: балл, Risk Grade A-E, уверенность модели и fraud-score.

Контракт ScoringModel: на входе плоские признаки Features.values и контекст (профиль и заявка
в формате контракта ML), на выходе ScoringOutput. Реализация выбирается настройкой SCORING_MODEL:
rules - прозрачная модель на правилах, ml - сервис инференса ML (ml/service) с откатом на правила.
Скоринг - вход для политики, а не кредитное решение.
"""

import asyncio
import json
import logging
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
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


@dataclass(frozen=True)
class ScoringContext:
    """Профиль заёмщика и заявка в формате docs/credit_mmb_data_model_updated.md -
    вход модели ML. None, если профиль собрать не удалось (не ответил источник)."""

    profile: dict[str, Any] | None = None
    application: dict[str, Any] | None = None


class ScoringModel(Protocol):
    async def score(
        self, features: Mapping[str, Any], context: ScoringContext | None = None
    ) -> ScoringOutput: ...


def grade_for(score: int) -> RiskGrade:
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return RiskGrade.E


class RuleBasedScoring:
    """Объяснимая модель на правилах до появления модели ML."""

    version = "rules-1"

    async def score(
        self, features: Mapping[str, Any], context: ScoringContext | None = None
    ) -> ScoringOutput:
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


logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    """Деньги в контракте ML - числа, даты - ISO."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Не сериализуется в JSON: {type(value).__name__}")


# Вероятность дефолта (калиброванная, на синтетических метках) -> Risk Grade
PD_GRADE_BANDS = (
    (Decimal("0.03"), RiskGrade.A),
    (Decimal("0.06"), RiskGrade.B),
    (Decimal("0.12"), RiskGrade.C),
    (Decimal("0.25"), RiskGrade.D),
)


def grade_for_pd(pd: Decimal) -> RiskGrade:
    for threshold, grade in PD_GRADE_BANDS:
        if pd <= threshold:
            return grade
    return RiskGrade.E


# Опорные точки «вероятность дефолта -> балл» на границах грейдов: балл и грейд согласованы
# со шкалой GRADE_BANDS (A от 800, B от 720, C от 650, D от 580)
_PD_SCORE_POINTS = (
    (Decimal("0"), MAX_SCORE),
    (Decimal("0.03"), 800),
    (Decimal("0.06"), 720),
    (Decimal("0.12"), 650),
    (Decimal("0.25"), 580),
    (Decimal("1"), MIN_SCORE),
)


def score_for_pd(pd: Decimal) -> int:
    """Балл 300-900: кусочно-линейно между опорными точками."""
    pd = min(max(pd, Decimal(0)), Decimal(1))
    for (pd_lo, score_lo), (pd_hi, score_hi) in zip(
        _PD_SCORE_POINTS, _PD_SCORE_POINTS[1:], strict=False
    ):
        if pd <= pd_hi:
            share = (pd - pd_lo) / (pd_hi - pd_lo)
            return round(score_lo + (score_hi - score_lo) * share)
    return MIN_SCORE


class MLServiceScoring:
    """Модель ML через HTTP-сервис. Вероятность дефолта и SHAP-факторы - от модели;
    уверенность и fraud-score - по полноте и противоречивости данных, как у правил
    (модель их не отдаёт). Если сервис недоступен или данные не проходят контракт
    признаков, используется модель на правилах - демо не зависит от ML-сервиса."""

    def __init__(self, fallback: RuleBasedScoring) -> None:
        self.fallback = fallback

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        request = urllib.request.Request(
            f"{settings.ml_service_url}/score",
            data=json.dumps(payload, ensure_ascii=False, default=_json_default).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=settings.ml_timeout_seconds) as response:
            return json.load(response)

    async def score(
        self, features: Mapping[str, Any], context: ScoringContext | None = None
    ) -> ScoringOutput:
        rules = await self.fallback.score(features)
        if context is None or context.profile is None or context.application is None:
            return replace(rules, model_version=f"{rules.model_version} (нет данных для ML)")
        try:
            result = await asyncio.to_thread(
                self._post, {"profile": context.profile, "application": context.application}
            )
        except Exception as exc:  # сеть, 422 по контракту признаков, 5xx
            logger.warning("ML-скоринг недоступен, используются правила: %s", exc)
            return replace(rules, model_version=f"{rules.model_version} (ML недоступен)")

        pd = Decimal(str(result["calibrated_probability"]))
        factors = [
            ScoringFactor(
                code=item["feature"],
                value=features.get(item["feature"]),
                # SHAP в логитах риска: + повышает риск, у нас + снижает
                impact=-round(item["impact_log_odds"] * 100),
                description=item["name_ru"],
            )
            for item in result.get("risk_increasing_factors", [])
            + result.get("risk_reducing_factors", [])
        ]
        return ScoringOutput(
            model_version=f"ml-{result['model']}-{result['calibration']}",
            score=score_for_pd(pd),
            risk_grade=grade_for_pd(pd),
            confidence=rules.confidence,
            fraud_score=rules.fraud_score,
            factors=factors,
        )


_RULES = RuleBasedScoring()
_MODELS: dict[str, ScoringModel] = {"rules": _RULES, "ml": MLServiceScoring(_RULES)}


def get_scoring_model() -> ScoringModel:
    return _MODELS[get_settings().scoring_model]
