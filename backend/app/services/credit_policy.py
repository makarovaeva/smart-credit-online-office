"""Кредитная политика: стоп-факторы, основания эскалации и контр-предложения ИИ.

Синхронизировано с фреймом «Кредитная политика» на доске Figma и docs/application-lifecycle.md.
Результат - рекомендация ИИ для AI Credit Memo, а не кредитное решение: финальное решение
всегда за андеррайтером. Исключение - красная зона (стоп-фактор), это автоотказ.
"""

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from app.models.enums import (
    AiRecommendation,
    AlternativeOfferKind,
    CollateralType,
    CounterOfferScenario,
    EscalationReasonCode,
    RiskZone,
    StopFactorCategory,
    StopFactorCode,
)

Scenario = CounterOfferScenario
Escalation = EscalationReasonCode


@dataclass(frozen=True)
class PolicyThresholds:
    # Лимит автоодобрения: меньшая из величин
    auto_approval_amount: Decimal = Decimal("5000000")
    auto_approval_revenue_share: Decimal = Decimal("0.20")
    # Ниже - стоп-фактор, от min_dscr - зелёная зона
    stop_dscr: Decimal = Decimal("0.9")
    min_dscr: Decimal = Decimal("1.1")
    max_debt_burden: Decimal = Decimal("0.50")
    max_ltv: Decimal = Decimal("0.70")
    max_negative_cash_flow_months: int = 3
    min_confidence: Decimal = Decimal("0.80")
    min_business_age_months: int = 12
    # Падение выручки, при котором ставка растёт на риск-надбавку
    revenue_drop_premium_from: Decimal = Decimal("0.20")
    revenue_drop_premium_to: Decimal = Decimal("0.30")
    risk_premium: Decimal = Decimal("2.00")
    # Шаг округления суммы контр-предложения
    amount_step: Decimal = Decimal("1000")


DEFAULT_THRESHOLDS = PolicyThresholds()

# Дисконт к рыночной стоимости залога для LTV - верхняя граница диапазона с доски
COLLATERAL_DISCOUNTS: dict[CollateralType, Decimal] = {
    CollateralType.COMMERCIAL_REAL_ESTATE: Decimal("0.30"),
    CollateralType.RESIDENTIAL_REAL_ESTATE: Decimal("0.25"),
    CollateralType.VEHICLE: Decimal("0.50"),
    CollateralType.EQUIPMENT: Decimal("0.60"),
    CollateralType.INVENTORY: Decimal("0.70"),
}

STOP_FACTORS: dict[StopFactorCode, tuple[StopFactorCategory, str]] = {
    StopFactorCode.BANKRUPTCY: (StopFactorCategory.LEGAL, "Действующее банкротство"),
    StopFactorCode.OBSERVATION_PROCEDURE: (StopFactorCategory.LEGAL, "Процедура наблюдения"),
    StopFactorCode.ACCOUNTS_BLOCKED_115FZ: (
        StopFactorCategory.LEGAL,
        "Счета заблокированы по 115-ФЗ",
    ),
    StopFactorCode.SANCTIONED_OWNER: (
        StopFactorCategory.LEGAL,
        "Собственники в санкционных списках",
    ),
    StopFactorCode.PROHIBITED_ACTIVITY: (StopFactorCategory.LEGAL, "Запрещённая деятельность"),
    StopFactorCode.NEGATIVE_CASH_FLOW: (
        StopFactorCategory.FINANCIAL,
        "Отрицательный Cash Flow более 3 месяцев подряд",
    ),
    StopFactorCode.LOW_DSCR: (StopFactorCategory.FINANCIAL, "DSCR ниже 0,9"),
    StopFactorCode.MASS_ADDRESS: (StopFactorCategory.FICTITIOUS, "Массовый адрес регистрации"),
    StopFactorCode.MASS_DIRECTOR: (StopFactorCategory.FICTITIOUS, "Массовый директор"),
    StopFactorCode.NO_EMPLOYEES: (StopFactorCategory.FICTITIOUS, "Нет сотрудников"),
    StopFactorCode.NO_TAX_ACTIVITY: (StopFactorCategory.FICTITIOUS, "Нет налоговой активности"),
}

ESCALATION_DESCRIPTIONS: dict[EscalationReasonCode, str] = {
    Escalation.LOW_CONFIDENCE: "Уверенность модели ниже 80%",
    Escalation.YOUNG_BUSINESS: "Бизнес существует менее года",
    Escalation.CONFLICTING_DATA: "Конфликтующие данные из разных источников",
    Escalation.HIGH_LTV: (
        "LTV 70% и выше: уменьшить сумму, добавить залог или гарантию Корпорации МСП"
    ),
    Escalation.WEAK_CREDIT_HISTORY: "Слабая кредитная история",
    Escalation.SEVERE_REVENUE_DROP: "Падение выручки более 30%",
    Escalation.NO_COUNTER_OFFER: "Контр-предложение не приводит показатели к зелёной зоне",
    Escalation.MISSING_EXTERNAL_DATA: "Не ответил внешний источник данных",
}


@dataclass(frozen=True)
class RiskSignals:
    """Результаты проверок внешних источников и анализа документов."""

    # Юридические стоп-факторы и признаки фиктивности, найденные проверками
    flags: frozenset[StopFactorCode] = frozenset()
    # Самая длинная серия месяцев подряд с отрицательным Cash Flow
    negative_cash_flow_months: int = 0
    model_confidence: Decimal = Decimal("1")
    business_age_months: int = 120
    conflicting_data: bool = False
    weak_credit_history: bool = False
    # Падение выручки, доля 0..1
    revenue_drop: Decimal = Decimal("0")
    # Не ответил хотя бы один внешний источник: решение на неполных данных
    missing_data: bool = False


@dataclass(frozen=True)
class PolicyInput:
    amount: Decimal
    term_months: int
    # Базовая ставка продукта, % годовых
    base_rate: Decimal
    min_amount: Decimal
    max_term_months: int
    annual_revenue: Decimal
    ebitda: Decimal
    # Годовые платежи по действующим кредитам и лизингу
    existing_annual_debt_service: Decimal
    collateral_type: CollateralType | None = None
    collateral_market_value: Decimal | None = None
    signals: RiskSignals = field(default_factory=RiskSignals)


@dataclass(frozen=True)
class Terms:
    amount: Decimal
    term_months: int
    rate: Decimal


@dataclass(frozen=True)
class Metrics:
    dscr: Decimal
    # None, если EBITDA <= 0
    debt_burden: Decimal | None
    # None без залога
    ltv: Decimal | None


@dataclass(frozen=True)
class Adjustment:
    scenario: CounterOfferScenario
    field: str
    old_value: Decimal | int
    new_value: Decimal | int
    description: str


@dataclass(frozen=True)
class AlternativeOffer:
    kind: AlternativeOfferKind
    terms: Terms
    metrics: Metrics
    monthly_payment: Decimal
    description: str


@dataclass(frozen=True)
class PolicyResult:
    zone: RiskZone
    recommendation: AiRecommendation
    requested_metrics: Metrics
    stop_factors: list[StopFactorCode]
    escalation_reasons: list[EscalationReasonCode]
    # Для красной зоны - None
    recommended_terms: Terms | None = None
    recommended_metrics: Metrics | None = None
    adjustments: list[Adjustment] = field(default_factory=list)
    # Варианты условий, если запрошенные не проходят зелёную зону
    alternatives: list[AlternativeOffer] = field(default_factory=list)


def monthly_payment(amount: Decimal, term_months: int, rate: Decimal) -> Decimal:
    """Аннуитетный платёж."""
    r = rate / Decimal(1200)
    if r == 0:
        return amount / term_months
    factor = (1 + r) ** term_months
    return amount * r * factor / (factor - 1)


def max_amount_for_payment(payment: Decimal, term_months: int, rate: Decimal) -> Decimal:
    r = rate / Decimal(1200)
    if r == 0:
        return payment * term_months
    factor = (1 + r) ** term_months
    return payment * (factor - 1) / (r * factor)


def collateral_value(data: PolicyInput) -> Decimal | None:
    """Рыночная стоимость залога с дисконтом - знаменатель LTV."""
    if data.collateral_type is None or not data.collateral_market_value:
        return None
    return data.collateral_market_value * (1 - COLLATERAL_DISCOUNTS[data.collateral_type])


def calculate_metrics(data: PolicyInput, terms: Terms) -> Metrics:
    """DSCR = EBITDA / Debt Service, Debt Burden = Debt Service / EBITDA,
    LTV = сумма / (рыночная стоимость * (1 - дисконт))."""
    debt_service = data.existing_annual_debt_service + 12 * monthly_payment(
        terms.amount, terms.term_months, terms.rate
    )
    pledged = collateral_value(data)
    return Metrics(
        dscr=data.ebitda / debt_service,
        debt_burden=debt_service / data.ebitda if data.ebitda > 0 else None,
        ltv=terms.amount / pledged if pledged else None,
    )


def evaluate(data: PolicyInput, t: PolicyThresholds = DEFAULT_THRESHOLDS) -> PolicyResult:
    requested = Terms(data.amount, data.term_months, data.base_rate)
    requested_metrics = calculate_metrics(data, requested)

    stop_factors = _stop_factors(data, requested_metrics, t)
    if stop_factors:
        return PolicyResult(
            zone=RiskZone.RED,
            recommendation=AiRecommendation.DECLINE,
            requested_metrics=requested_metrics,
            stop_factors=stop_factors,
            escalation_reasons=[],
        )

    escalation = _escalation_reasons(data, requested_metrics, t)
    terms, adjustments = _counter_offer(data, requested, t)
    metrics = calculate_metrics(data, terms)
    if not _is_green(data, terms, metrics, t):
        escalation.append(Escalation.NO_COUNTER_OFFER)

    # Ставка с риск-надбавкой одна для всех вариантов
    at_rate = Terms(data.amount, data.term_months, terms.rate)
    alternatives = (
        []
        if _is_green(data, at_rate, calculate_metrics(data, at_rate), t)
        else _alternatives(data, terms.rate, t)
    )
    return PolicyResult(
        zone=RiskZone.YELLOW if escalation else RiskZone.GREEN,
        recommendation=(
            AiRecommendation.COUNTER_OFFER if adjustments else AiRecommendation.APPROVE
        ),
        requested_metrics=requested_metrics,
        stop_factors=[],
        escalation_reasons=escalation,
        recommended_terms=terms,
        recommended_metrics=metrics,
        adjustments=adjustments,
        alternatives=alternatives,
    )


def _stop_factors(data: PolicyInput, metrics: Metrics, t: PolicyThresholds) -> list[StopFactorCode]:
    found = set(data.signals.flags)
    if data.signals.negative_cash_flow_months > t.max_negative_cash_flow_months:
        found.add(StopFactorCode.NEGATIVE_CASH_FLOW)
    if metrics.dscr < t.stop_dscr:
        found.add(StopFactorCode.LOW_DSCR)
    return [code for code in StopFactorCode if code in found]


def _escalation_reasons(
    data: PolicyInput, metrics: Metrics, t: PolicyThresholds
) -> list[EscalationReasonCode]:
    s = data.signals
    checks = {
        Escalation.LOW_CONFIDENCE: s.model_confidence < t.min_confidence,
        Escalation.YOUNG_BUSINESS: s.business_age_months < t.min_business_age_months,
        Escalation.CONFLICTING_DATA: s.conflicting_data,
        Escalation.HIGH_LTV: metrics.ltv is not None and metrics.ltv >= t.max_ltv,
        Escalation.WEAK_CREDIT_HISTORY: s.weak_credit_history,
        Escalation.SEVERE_REVENUE_DROP: s.revenue_drop > t.revenue_drop_premium_to,
        Escalation.MISSING_EXTERNAL_DATA: s.missing_data,
    }
    return [code for code, hit in checks.items() if hit]


def _auto_approval_limit(data: PolicyInput, t: PolicyThresholds) -> Decimal:
    return min(t.auto_approval_amount, data.annual_revenue * t.auto_approval_revenue_share)


def _is_green(data: PolicyInput, terms: Terms, metrics: Metrics, t: PolicyThresholds) -> bool:
    """Целевые значения сценариев включительно: сумма, уменьшенная до LTV = 70%, проходит."""
    return (
        data.min_amount <= terms.amount <= _auto_approval_limit(data, t)
        and metrics.dscr >= t.min_dscr
        and metrics.debt_burden is not None
        and metrics.debt_burden <= t.max_debt_burden
        and (metrics.ltv is None or metrics.ltv <= t.max_ltv)
    )


def _round_amount(amount: Decimal, t: PolicyThresholds) -> Decimal:
    return (amount / t.amount_step).to_integral_value(ROUND_DOWN) * t.amount_step


def _counter_offer(
    data: PolicyInput, terms: Terms, t: PolicyThresholds
) -> tuple[Terms, list[Adjustment]]:
    """Сценарии 1-5 по порядку: каждый возвращает в зелёную зону с новыми условиями.
    Ставку из сценария 5 фиксируем заранее: сумму и срок считаем уже от итогового платежа."""
    adjustments: list[Adjustment] = []
    s = data.signals
    base_rate = terms.rate
    needs_premium = s.weak_credit_history or s.revenue_drop >= t.revenue_drop_premium_from
    if needs_premium:
        terms = Terms(terms.amount, terms.term_months, base_rate + t.risk_premium)

    def change_amount(new: Decimal, scenario: Scenario, description: str) -> None:
        nonlocal terms
        new = _round_amount(new, t)
        if new < terms.amount:
            adjustments.append(Adjustment(scenario, "amount", terms.amount, new, description))
            terms = Terms(new, terms.term_months, terms.rate)

    # 1. Лимит автоодобрения
    limit = _auto_approval_limit(data, t)
    if terms.amount > limit:
        change_amount(
            limit,
            Scenario.AUTO_APPROVAL_LIMIT,
            "Сумма снижена до лимита: меньшая из величин 5 млн ₽ и 20% годового оборота",
        )

    # 2. DSCR ниже минимального - увеличиваем срок, пока DSCR не станет >= min_dscr
    if calculate_metrics(data, terms).dscr < t.min_dscr:
        for term in range(terms.term_months + 1, data.max_term_months + 1):
            candidate = Terms(terms.amount, term, terms.rate)
            if calculate_metrics(data, candidate).dscr >= t.min_dscr:
                adjustments.append(
                    Adjustment(
                        Scenario.TERM_EXTENSION,
                        "term_months",
                        terms.term_months,
                        term,
                        f"Срок увеличен, платёж пересчитан: DSCR ≥ {t.min_dscr}",
                    )
                )
                terms = candidate
                break

    # 3. Debt Burden >= 50% - уменьшаем сумму
    if (burden := calculate_metrics(data, terms).debt_burden) is not None and (
        burden >= t.max_debt_burden
    ):
        max_payment = (t.max_debt_burden * data.ebitda - data.existing_annual_debt_service) / 12
        if max_payment > 0:
            change_amount(
                max_amount_for_payment(max_payment, terms.term_months, terms.rate),
                Scenario.DEBT_BURDEN_AMOUNT_REDUCTION,
                "Сумма уменьшена до долговой нагрузки не выше 50%",
            )

    # 4. LTV >= 70% - уменьшаем сумму; добавить залог или гарантию МСП решает аналитик
    pledged = collateral_value(data)
    if pledged and terms.amount / pledged >= t.max_ltv:
        change_amount(
            pledged * t.max_ltv,
            Scenario.LTV_AMOUNT_REDUCTION,
            "Сумма уменьшена до LTV не выше 70%",
        )

    # 5. Риск выше среднего - сумма сохраняется, ставка растёт на риск-надбавку
    if needs_premium:
        adjustments.append(
            Adjustment(
                Scenario.RISK_PREMIUM,
                "rate",
                base_rate,
                terms.rate,
                f"Ставка увеличена на риск-надбавку {t.risk_premium}%",
            )
        )

    return terms, adjustments


# --- Альтернативные варианты при пограничном риске ---


def _amount_caps(data: PolicyInput, t: PolicyThresholds) -> Decimal:
    """Жёсткие ограничения суммы, не зависящие от срока: запрос, лимит автоодобрения, LTV."""
    caps = [data.amount, _auto_approval_limit(data, t)]
    if pledged := collateral_value(data):
        caps.append(pledged * t.max_ltv)
    return min(caps)


def _max_amount(
    data: PolicyInput, term_months: int, rate: Decimal, t: PolicyThresholds
) -> Decimal | None:
    """Наибольшая сумма на сроке, при которой DSCR >= min_dscr и Debt Burden <= max."""
    max_debt_service = min(data.ebitda / t.min_dscr, data.ebitda * t.max_debt_burden)
    payment = (max_debt_service - data.existing_annual_debt_service) / 12
    if payment <= 0:
        return None
    by_payment = max_amount_for_payment(payment, term_months, rate)
    amount = _round_amount(min(_amount_caps(data, t), by_payment), t)
    return amount if amount >= data.min_amount else None


def _min_term(data: PolicyInput, amount: Decimal, rate: Decimal, t: PolicyThresholds) -> int | None:
    for term in range(data.term_months, data.max_term_months + 1):
        terms = Terms(amount, term, rate)
        if _is_green(data, terms, calculate_metrics(data, terms), t):
            return term
    return None


def _format_rub(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _alternatives(data: PolicyInput, rate: Decimal, t: PolicyThresholds) -> list[AlternativeOffer]:
    candidates: list[tuple[AlternativeOfferKind, Terms | None]] = []
    keep_amount = _round_amount(_amount_caps(data, t), t)
    term = _min_term(data, keep_amount, rate, t)
    # Проходит без продления - это уже вариант «меньше сумма»
    longer = term is not None and term > data.term_months
    candidates.append(
        (AlternativeOfferKind.LONGER_TERM, Terms(keep_amount, term, rate) if longer else None)
    )
    for kind, term in (
        (AlternativeOfferKind.LOWER_AMOUNT, data.term_months),
        (AlternativeOfferKind.MAX_TERM, data.max_term_months),
    ):
        amount = _max_amount(data, term, rate, t)
        candidates.append((kind, Terms(amount, term, rate) if amount else None))

    offers: list[AlternativeOffer] = []
    for kind, terms in candidates:
        if terms is None or any(o.terms == terms for o in offers):
            continue
        payment = monthly_payment(terms.amount, terms.term_months, terms.rate)
        offers.append(
            AlternativeOffer(
                kind=kind,
                terms=terms,
                metrics=calculate_metrics(data, terms),
                monthly_payment=payment.quantize(Decimal("0.01")),
                description=(
                    f"{_format_rub(terms.amount)} ₽ на {terms.term_months} мес. под {terms.rate}%, "
                    f"платёж {_format_rub(payment)} ₽/мес."
                ),
            )
        )
    return offers
