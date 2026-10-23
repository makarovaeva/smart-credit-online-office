"""Кредитный конвейер: обогащение данных -> скоринг -> кредитная политика -> маршрутизация.

Два прогона:
- после согласий: data_collection -> pre_approved (предварительный расчёт);
- после подачи: submitted -> ai_verification -> ai_financial_analysis -> ai_risk_scoring
  -> decision_routing -> underwriter_review | analyst_escalation | closed (автоотказ)
  или need_additional_data, если не хватает финансовых данных.

Каждый прогон - одна транзакция: при ошибке заявка остаётся на исходном этапе.
Финальное решение по зелёной и жёлтой зоне принимает андеррайтер.
"""

import logging
from dataclasses import replace
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    CreditMemo,
    CreditProduct,
    InfoRequest,
    PreApproval,
    ScoringResult,
)
from app.models.enums import (
    ActorType,
    ApplicationStatus,
    CloseReason,
    DocumentType,
    EscalationReasonCode,
    RiskGrade,
    RiskZone,
)
from app.services.credit_policy import (
    ESCALATION_DESCRIPTIONS,
    STOP_FACTORS,
    PolicyInput,
    PolicyResult,
    evaluate,
)
from app.services.enrichment import application_features, collect_external_data
from app.services.features import Features
from app.services.scoring import ScoringOutput, get_scoring_model
from app.services.transitions import transition

logger = logging.getLogger(__name__)

S = ApplicationStatus
SYSTEM = ActorType.SYSTEM

# Вероятность одобрения для предварительного расчёта по Risk Grade
GRADE_PROBABILITY = {
    RiskGrade.A: Decimal("0.90"),
    RiskGrade.B: Decimal("0.80"),
    RiskGrade.C: Decimal("0.65"),
    RiskGrade.D: Decimal("0.45"),
    RiskGrade.E: Decimal("0.25"),
}
# Жёлтая зона: решение после ручного разбора - шансы ниже
YELLOW_PROBABILITY_FACTOR = Decimal("0.8")
RED_PROBABILITY = Decimal("0.05")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _policy_input(
    application: Application, product: CreditProduct, features: Features, scoring: ScoringOutput
) -> PolicyInput | None:
    """Отчётность из ФНС приоритетнее анкеты; без выручки и EBITDA оценка невозможна."""
    values = features.values
    revenue = (
        _dec(values["fin_annual_turnover"])
        if "fin_annual_turnover" in values
        else application.annual_revenue
    )
    ebitda = _dec(values["fin_ebitda"]) if "fin_ebitda" in values else application.annual_ebitda
    if revenue is None or ebitda is None:
        return None
    debt_service = features.existing_annual_debt_service
    if debt_service is None:
        debt_service = (application.monthly_debt_payments or Decimal(0)) * 12
    return PolicyInput(
        amount=application.requested_amount,
        term_months=application.requested_term_months,
        base_rate=product.base_rate,
        min_amount=product.min_amount,
        max_term_months=product.max_term_months,
        annual_revenue=revenue,
        ebitda=ebitda,
        existing_annual_debt_service=debt_service,
        collateral_type=application.collateral_type if application.has_collateral else None,
        collateral_market_value=(
            application.collateral_market_value if application.has_collateral else None
        ),
        signals=replace(features.signals, model_confidence=scoring.confidence),
    )


async def _assess(
    session: AsyncSession, application: Application, product: CreditProduct
) -> tuple[Features, ScoringOutput, PolicyResult | None]:
    await collect_external_data(session, application)
    features = await application_features(session, application)
    scoring = await get_scoring_model().score(features.values)
    data = _policy_input(application, product, features, scoring)
    return features, scoring, evaluate(data) if data else None


def _escalation_items(codes: list[EscalationReasonCode]) -> list[dict[str, str]]:
    return [{"code": code, "description": ESCALATION_DESCRIPTIONS[code]} for code in codes]


# --- Предварительный расчёт ---


def _pre_approval(
    application: Application,
    product: CreditProduct,
    scoring: ScoringOutput,
    policy: PolicyResult | None,
) -> PreApproval:
    common = {
        "application_id": application.id,
        "collateral_required": product.requires_collateral,
    }
    if policy is None:
        return PreApproval(
            **common,
            approval_probability=Decimal("0.50"),
            amount_min=product.min_amount,
            amount_max=application.requested_amount,
            estimated_rate=product.base_rate,
            recommendations=[
                {
                    "code": "upload_financial_statements",
                    "message": "Загрузите бухгалтерскую отчётность - расчёт станет точнее",
                }
            ],
        )
    if policy.zone == RiskZone.RED:
        return PreApproval(
            **common,
            approval_probability=RED_PROBABILITY,
            amount_min=Decimal(0),
            amount_max=Decimal(0),
            estimated_rate=product.base_rate,
            recommendations=[
                {"code": code, "message": STOP_FACTORS[code][1]} for code in policy.stop_factors
            ],
        )
    terms = policy.recommended_terms
    assert terms is not None
    probability = GRADE_PROBABILITY[scoring.risk_grade]
    if policy.zone == RiskZone.YELLOW:
        probability *= YELLOW_PROBABILITY_FACTOR
    # Верхняя граница - лучший из вариантов: основной или альтернативный
    amount_max = max([terms.amount, *(o.terms.amount for o in policy.alternatives)])
    return PreApproval(
        **common,
        approval_probability=probability.quantize(Decimal("0.0001")),
        amount_min=min(product.min_amount, terms.amount),
        amount_max=amount_max,
        estimated_rate=terms.rate,
        recommendations=[{"code": a.scenario, "message": a.description} for a in policy.adjustments]
        + [
            {"code": f"alternative_{o.kind}", "message": f"Возможный вариант: {o.description}"}
            for o in policy.alternatives
        ]
        + [
            {
                "code": item["code"],
                "message": f"Заявку дополнительно проверит аналитик: {item['description'].lower()}",
            }
            for item in _escalation_items(policy.escalation_reasons)
        ],
    )


async def run_data_collection(session: AsyncSession, application: Application) -> None:
    """data_collection -> pre_approved: сбор данных и предварительный расчёт."""
    product = await session.get(CreditProduct, application.product_id)
    assert product is not None
    _, scoring, policy = await _assess(session, application, product)
    session.add(_pre_approval(application, product, scoring, policy))
    await transition(session, application, S.PRE_APPROVED, SYSTEM)
    await session.commit()


# --- Оценка заявки после подачи ---


def _ratio(value: Decimal | None) -> Decimal | None:
    return value.quantize(Decimal("0.0001")) if value is not None else None


def _scoring_result(
    application: Application, features: Features, scoring: ScoringOutput, policy: PolicyResult
) -> ScoringResult:
    metrics = policy.requested_metrics
    recommended = policy.recommended_metrics
    return ScoringResult(
        application_id=application.id,
        model_version=scoring.model_version,
        dscr=_ratio(metrics.dscr),
        debt_burden=_ratio(metrics.debt_burden),
        ltv=_ratio(metrics.ltv),
        metrics={
            "features": features.values,
            "recommended": (
                {
                    "dscr": str(_ratio(recommended.dscr)),
                    "debt_burden": str(_ratio(recommended.debt_burden)),
                    "ltv": str(_ratio(recommended.ltv)) if recommended.ltv else None,
                }
                if recommended
                else None
            ),
            "conflicts": features.conflicts,
            "missing_sources": [str(s) for s in features.missing_sources],
        },
        score=scoring.score,
        risk_grade=scoring.risk_grade,
        risk_zone=policy.zone,
        confidence=scoring.confidence,
        fraud_score=scoring.fraud_score,
        factors=[
            {"code": f.code, "value": f.value, "impact": f.impact, "description": f.description}
            for f in scoring.factors
        ],
        stop_factors=[
            {"code": code, "category": STOP_FACTORS[code][0], "description": STOP_FACTORS[code][1]}
            for code in policy.stop_factors
        ],
        escalation_reasons=_escalation_items(policy.escalation_reasons),
    )


def _memo_summary(features: Features, scoring: ScoringOutput, policy: PolicyResult) -> str:
    m = policy.requested_metrics
    lines = [
        f"Зона риска: {policy.zone}, Risk Grade {scoring.risk_grade} "
        f"(балл {scoring.score}, уверенность {scoring.confidence:.0%}).",
        f"На запрошенных условиях: DSCR {m.dscr:.2f}, "
        + (f"Debt Burden {m.debt_burden:.0%}" if m.debt_burden is not None else "EBITDA ≤ 0")
        + (f", LTV {m.ltv:.0%}." if m.ltv is not None else "."),
    ]
    lines += [f"Стоп-фактор: {STOP_FACTORS[c][1]}." for c in policy.stop_factors]
    lines += [f"Эскалация: {ESCALATION_DESCRIPTIONS[c]}." for c in policy.escalation_reasons]
    lines += [f"Контр-предложение: {a.description}." for a in policy.adjustments]
    lines += [f"Расхождение: {c}." for c in features.conflicts]
    lines += [f"Фактор скоринга: {f.description} ({f.impact:+d})." for f in scoring.factors]
    return "\n".join(lines)


def _credit_memo(
    application: Application,
    scoring_result: ScoringResult,
    features: Features,
    scoring: ScoringOutput,
    policy: PolicyResult,
) -> CreditMemo:
    terms = policy.recommended_terms
    conditions = []
    if EscalationReasonCode.HIGH_LTV in policy.escalation_reasons:
        conditions.append(
            {
                "code": "additional_collateral_or_sme_guarantee",
                "description": "Добавить залог или гарантию Корпорации МСП",
            }
        )
    return CreditMemo(
        application_id=application.id,
        scoring_result_id=scoring_result.id,
        summary=_memo_summary(features, scoring, policy),
        ai_recommendation=policy.recommendation,
        recommended_amount=terms.amount if terms else None,
        recommended_term_months=terms.term_months if terms else None,
        recommended_rate=terms.rate if terms else None,
        recommended_conditions=conditions,
        counter_offer_adjustments=[
            {
                "scenario": a.scenario,
                "field": a.field,
                "old_value": str(a.old_value),
                "new_value": str(a.new_value),
                "description": a.description,
            }
            for a in policy.adjustments
        ],
        alternative_offers=[
            {
                "kind": o.kind,
                "amount": f"{o.terms.amount:.2f}",
                "term_months": o.terms.term_months,
                "rate": f"{o.terms.rate:.2f}",
                "monthly_payment": str(o.monthly_payment),
                "dscr": str(_ratio(o.metrics.dscr)),
                "debt_burden": str(_ratio(o.metrics.debt_burden)),
                "ltv": str(_ratio(o.metrics.ltv)) if o.metrics.ltv is not None else None,
                "description": o.description,
            }
            for o in policy.alternatives
        ],
    )


async def _request_financials(session: AsyncSession, application: Application) -> None:
    session.add(
        InfoRequest(
            application_id=application.id,
            message=(
                "Не удалось получить финансовую отчётность из ФНС. Загрузите бухгалтерскую "
                "или управленческую отчётность за последний год"
            ),
            requested_document_types=[
                DocumentType.FINANCIAL_STATEMENT,
                DocumentType.MANAGEMENT_REPORT,
            ],
        )
    )
    await transition(session, application, S.NEED_ADDITIONAL_DATA, SYSTEM)


async def run_assessment(session: AsyncSession, application: Application) -> None:
    """От проверки данных до маршрутизации: андеррайтер, аналитик или автоотказ."""
    product = await session.get(CreditProduct, application.product_id)
    assert product is not None

    await transition(session, application, S.AI_VERIFICATION, SYSTEM)
    features, scoring, policy = await _assess(session, application, product)
    if policy is None:
        await _request_financials(session, application)
        await session.commit()
        return

    await transition(session, application, S.AI_FINANCIAL_ANALYSIS, SYSTEM)
    await transition(session, application, S.AI_RISK_SCORING, SYSTEM)
    scoring_result = _scoring_result(application, features, scoring, policy)
    session.add(scoring_result)
    await session.flush()
    session.add(_credit_memo(application, scoring_result, features, scoring, policy))

    await transition(session, application, S.DECISION_ROUTING, SYSTEM)
    match policy.zone:
        case RiskZone.RED:
            reasons = "; ".join(STOP_FACTORS[c][1] for c in policy.stop_factors)
            await transition(
                session,
                application,
                S.CLOSED,
                SYSTEM,
                comment=f"Автоматический отказ: {reasons}",
                close_reason=CloseReason.AUTO_DECLINED,
            )
        case RiskZone.YELLOW:
            await transition(session, application, S.ANALYST_ESCALATION, SYSTEM)
        case RiskZone.GREEN:
            await transition(session, application, S.UNDERWRITER_REVIEW, SYSTEM)
    await session.commit()


async def run_safely(session: AsyncSession, application: Application, step) -> None:
    """Сбой конвейера не ломает команду клиента: она уже сохранена, заявка остаётся на этапе."""
    try:
        await step(session, application)
    except Exception:
        logger.exception("Конвейер упал на заявке %s (%s)", application.id, step.__name__)
        await session.rollback()
        await session.refresh(application)
