from app.models.enums import ApplicationStatus, DecisionType
from app.schemas.application import ClientStatus
from app.services.client_status import client_status

S = ApplicationStatus


def test_every_status_has_client_status() -> None:
    for status in ApplicationStatus:
        client_status(status, None)


def test_internal_stages_are_hidden() -> None:
    for status in (S.DECISION_ROUTING, S.ANALYST_ESCALATION, S.UNDERWRITER_REVIEW):
        assert client_status(status, None) == ClientStatus.UNDER_REVIEW


def test_offer_shows_approval_or_counter_offer() -> None:
    assert client_status(S.OFFER_GENERATED, DecisionType.APPROVED) == ClientStatus.APPROVED
    assert (
        client_status(S.OFFER_GENERATED, DecisionType.CONDITIONAL_APPROVAL)
        == ClientStatus.COUNTER_OFFER
    )
