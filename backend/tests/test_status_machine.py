import pytest

from app.models.enums import ActorType, ApplicationStatus
from app.services.status_machine import (
    FINAL_STATUSES,
    TRANSITIONS,
    TransitionError,
    can_transition,
    ensure_transition,
)

S = ApplicationStatus
A = ActorType


def test_green_zone_path_is_allowed() -> None:
    path = [
        (S.DRAFT, S.DATA_COLLECTION, A.CLIENT),
        (S.DATA_COLLECTION, S.PRE_APPROVED, A.SYSTEM),
        (S.PRE_APPROVED, S.SUBMITTED, A.CLIENT),
        (S.SUBMITTED, S.AI_VERIFICATION, A.SYSTEM),
        (S.AI_VERIFICATION, S.AI_RISK_SCORING, A.SYSTEM),
        (S.AI_RISK_SCORING, S.DECISION_ROUTING, A.SYSTEM),
        (S.DECISION_ROUTING, S.AI_FINANCIAL_ANALYSIS, A.SYSTEM),
        (S.AI_FINANCIAL_ANALYSIS, S.UNDERWRITER_REVIEW, A.SYSTEM),
        (S.UNDERWRITER_REVIEW, S.OFFER_GENERATED, A.UNDERWRITER),
        (S.OFFER_GENERATED, S.OFFER_ACCEPTED, A.CLIENT),
        (S.OFFER_ACCEPTED, S.CONTRACT_GENERATION, A.SYSTEM),
        (S.CONTRACT_GENERATION, S.E_SIGN, A.SYSTEM),
        (S.E_SIGN, S.DISBURSEMENT, A.CLIENT),
        (S.DISBURSEMENT, S.COMPLETED, A.SYSTEM),
    ]
    for current, target, actor in path:
        ensure_transition(current, target, actor)


def test_analyst_escalation_returns_to_underwriter() -> None:
    ensure_transition(S.DECISION_ROUTING, S.ANALYST_ESCALATION, A.SYSTEM)
    ensure_transition(S.ANALYST_ESCALATION, S.ANALYST_COMPLETED, A.CREDIT_ANALYST)
    ensure_transition(S.ANALYST_COMPLETED, S.UNDERWRITER_REVIEW, A.SYSTEM)


def test_only_underwriter_decides() -> None:
    for actor in (A.SYSTEM, A.CREDIT_ANALYST, A.CLIENT):
        assert not can_transition(S.UNDERWRITER_REVIEW, S.OFFER_GENERATED, actor)
        assert not can_transition(S.UNDERWRITER_REVIEW, S.CLOSED, actor)


def test_auto_decline_only_on_routing() -> None:
    assert can_transition(S.DECISION_ROUTING, S.CLOSED, A.SYSTEM)
    for status in (S.AI_VERIFICATION, S.AI_FINANCIAL_ANALYSIS, S.AI_RISK_SCORING):
        assert not can_transition(status, S.CLOSED, A.SYSTEM)


def test_financial_analysis_only_on_green_route() -> None:
    """По доске от 23.10 финанализ идёт после маршрутизации и только к андеррайтеру."""
    assert not can_transition(S.AI_VERIFICATION, S.AI_FINANCIAL_ANALYSIS, A.SYSTEM)
    assert not can_transition(S.DECISION_ROUTING, S.UNDERWRITER_REVIEW, A.SYSTEM)
    assert not can_transition(S.AI_FINANCIAL_ANALYSIS, S.ANALYST_ESCALATION, A.SYSTEM)


def test_documents_return_to_verification_or_underwriter() -> None:
    ensure_transition(S.NEED_ADDITIONAL_DATA, S.AI_VERIFICATION, A.CLIENT)
    ensure_transition(S.NEED_ADDITIONAL_DATA, S.UNDERWRITER_REVIEW, A.CLIENT)
    assert not can_transition(S.NEED_ADDITIONAL_DATA, S.AI_FINANCIAL_ANALYSIS, A.CLIENT)


def test_underwriter_requests_analyst_expertise() -> None:
    ensure_transition(S.UNDERWRITER_REVIEW, S.ANALYST_ESCALATION, A.UNDERWRITER)
    ensure_transition(S.ANALYST_ESCALATION, S.ANALYST_COMPLETED, A.CREDIT_ANALYST)
    ensure_transition(S.ANALYST_COMPLETED, S.UNDERWRITER_REVIEW, A.SYSTEM)


def test_unknown_transition_raises() -> None:
    with pytest.raises(TransitionError):
        ensure_transition(S.DRAFT, S.COMPLETED, A.SYSTEM)


def test_final_statuses_have_no_outgoing_transitions() -> None:
    assert not [pair for pair in TRANSITIONS if pair[0] in FINAL_STATUSES]


def test_every_status_is_reachable() -> None:
    reachable = {target for _, target in TRANSITIONS} | {S.DRAFT}
    assert reachable == set(ApplicationStatus)
