"""Решения сотрудников банка: заключение кредитного аналитика и решение андеррайтера."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Application, CreditDecision, CreditMemo, InfoRequest, User
from app.models.enums import (
    ActorType,
    ApplicationStatus,
    CloseReason,
    DecisionType,
    MoreInfoTarget,
)
from app.schemas.decision import AnalystConclusionRequest, UnderwriterDecisionRequest
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError
from app.services.status_machine import ensure_transition
from app.services.transitions import transition

S = ApplicationStatus


async def get_application_for_update(
    session: AsyncSession, application_id: uuid.UUID
) -> Application:
    application = await session.scalar(
        select(Application).where(Application.id == application_id).with_for_update()
    )
    if application is None:
        raise NotFoundError("Заявка не найдена")
    return application


async def latest_memo(session: AsyncSession, application_id: uuid.UUID) -> CreditMemo:
    memo = await session.scalar(
        select(CreditMemo)
        .where(CreditMemo.application_id == application_id)
        .order_by(CreditMemo.created_at.desc())
        .limit(1)
    )
    if memo is None:
        raise ConflictError("По заявке нет AI Credit Memo")
    return memo


async def complete_analysis(
    session: AsyncSession, analyst: User, application_id: uuid.UUID, body: AnalystConclusionRequest
) -> CreditMemo:
    application = await get_application_for_update(session, application_id)
    ensure_transition(application.status, S.ANALYST_COMPLETED, ActorType.CREDIT_ANALYST)
    memo = await latest_memo(session, application.id)

    memo.analyst_id = analyst.id
    memo.analyst_conclusion = body.conclusion
    memo.analyst_recommendation = body.recommendation
    memo.analyst_completed_at = datetime.now(UTC)
    # Условия меняются, только если аналитик их передал
    for field in ("recommended_amount", "recommended_term_months", "recommended_rate"):
        if field in body.model_fields_set:
            setattr(memo, field, getattr(body, field))
    if "recommended_conditions" in body.model_fields_set:
        memo.recommended_conditions = [c.model_dump() for c in body.recommended_conditions]

    await transition(
        session, application, S.ANALYST_COMPLETED, ActorType.CREDIT_ANALYST, analyst.id
    )
    await transition(session, application, S.UNDERWRITER_REVIEW, ActorType.SYSTEM)
    application.assignee_id = None
    await session.commit()
    return memo


def _target_status(body: UnderwriterDecisionRequest) -> ApplicationStatus:
    """Куда ведёт решение; заодно проверяет, что для него переданы нужные данные."""
    match body.decision_type:
        case DecisionType.APPROVED | DecisionType.CONDITIONAL_APPROVAL:
            if None in (body.approved_amount, body.approved_term_months, body.interest_rate):
                raise ValidationFailedError("Для одобрения нужны сумма, срок и ставка")
            return S.OFFER_GENERATED
        case DecisionType.DECLINED:
            if not body.reasons:
                raise ValidationFailedError("Для отказа нужна причина, понятная клиенту")
            return S.CLOSED
        case DecisionType.MORE_INFORMATION_REQUIRED:
            if body.more_info_target == MoreInfoTarget.CLIENT:
                if body.info_request is None:
                    raise ValidationFailedError("Укажите, какие документы запросить у клиента")
                return S.NEED_ADDITIONAL_DATA
            if body.more_info_target == MoreInfoTarget.CREDIT_ANALYST:
                if not body.comment:
                    raise ValidationFailedError("Укажите в comment, что проверить аналитику")
                return S.ANALYST_ESCALATION
            raise ValidationFailedError("Укажите more_info_target: client или credit_analyst")


def _with_alternative(
    body: UnderwriterDecisionRequest, memo: CreditMemo
) -> UnderwriterDecisionRequest:
    """Подставляет условия выбранного варианта из AI Credit Memo в незаполненные поля."""
    if body.decision_type != DecisionType.CONDITIONAL_APPROVAL:
        raise ValidationFailedError("Вариант условий выбирается только для контр-предложения")
    offer = next((o for o in memo.alternative_offers if o["kind"] == body.alternative_offer), None)
    if offer is None:
        raise ValidationFailedError("В AI Credit Memo нет такого варианта условий")
    defaults = {
        "approved_amount": Decimal(offer["amount"]),
        "approved_term_months": offer["term_months"],
        "interest_rate": Decimal(offer["rate"]),
    }
    return body.model_copy(update={k: v for k, v in defaults.items() if getattr(body, k) is None})


async def make_decision(
    session: AsyncSession,
    underwriter: User,
    application_id: uuid.UUID,
    body: UnderwriterDecisionRequest,
) -> CreditDecision:
    application = await get_application_for_update(session, application_id)
    memo = await latest_memo(session, application.id)
    if body.alternative_offer is not None:
        body = _with_alternative(body, memo)
    target = _target_status(body)
    ensure_transition(application.status, target, ActorType.UNDERWRITER)

    is_offer = target == S.OFFER_GENERATED
    is_final = body.decision_type != DecisionType.MORE_INFORMATION_REQUIRED
    now = datetime.now(UTC)
    decision = CreditDecision(
        application_id=application.id,
        credit_memo_id=memo.id,
        decision_type=body.decision_type,
        decided_by_id=underwriter.id,
        more_info_target=body.more_info_target if not is_final else None,
        comment=body.comment,
        reasons=[r.model_dump() for r in body.reasons],
        approved_amount=body.approved_amount if is_offer else None,
        approved_term_months=body.approved_term_months if is_offer else None,
        interest_rate=body.interest_rate if is_offer else None,
        conditions=[c.model_dump() for c in body.conditions] if is_offer else [],
        valid_until=(
            now + timedelta(days=get_settings().offer_validity_days) if is_offer else None
        ),
    )
    session.add(decision)

    if target == S.NEED_ADDITIONAL_DATA:
        assert body.info_request is not None
        session.add(
            InfoRequest(
                application_id=application.id,
                created_by_id=underwriter.id,
                message=body.info_request.message,
                requested_document_types=body.info_request.requested_document_types,
            )
        )
    await transition(
        session,
        application,
        target,
        ActorType.UNDERWRITER,
        underwriter.id,
        comment=body.comment,
        close_reason=CloseReason.UNDERWRITER_DECLINED if target == S.CLOSED else None,
    )
    if is_final:
        application.decided_at = now
    application.assignee_id = None
    await session.commit()
    return decision
