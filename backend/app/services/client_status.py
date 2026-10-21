"""Статус заявки глазами клиента - по пользовательскому пути на доске Figma."""

from app.models.enums import ApplicationStatus, DecisionType
from app.schemas.application import ClientStatus

S = ApplicationStatus

_BY_STATUS: dict[ApplicationStatus, ClientStatus] = {
    S.DRAFT: ClientStatus.DRAFT,
    S.DATA_COLLECTION: ClientStatus.DRAFT,
    S.PRE_APPROVED: ClientStatus.DRAFT,
    S.SUBMITTED: ClientStatus.CREATED,
    S.AI_VERIFICATION: ClientStatus.UNDER_REVIEW,
    S.NEED_ADDITIONAL_DATA: ClientStatus.DOCUMENTS_REQUIRED,
    S.AI_FINANCIAL_ANALYSIS: ClientStatus.UNDER_REVIEW,
    S.AI_RISK_SCORING: ClientStatus.UNDER_REVIEW,
    S.DECISION_ROUTING: ClientStatus.UNDER_REVIEW,
    S.ANALYST_ESCALATION: ClientStatus.UNDER_REVIEW,
    S.ANALYST_COMPLETED: ClientStatus.UNDER_REVIEW,
    S.UNDERWRITER_REVIEW: ClientStatus.UNDER_REVIEW,
    S.DISBURSEMENT: ClientStatus.SIGNED,
    S.COMPLETED: ClientStatus.DISBURSED,
    S.OFFER_REJECTED: ClientStatus.CLOSED,
    S.CLOSED: ClientStatus.CLOSED,
}

# От оффера до подписания клиент видит, одобрено или контр-предложение
_OFFER_STATUSES = frozenset({S.OFFER_GENERATED, S.OFFER_ACCEPTED, S.CONTRACT_GENERATION, S.E_SIGN})


def client_status(status: ApplicationStatus, decision: DecisionType | None) -> ClientStatus:
    """decision - последнее решение андеррайтера, нужно только на этапах оффера."""
    if status in _OFFER_STATUSES:
        if decision == DecisionType.CONDITIONAL_APPROVAL:
            return ClientStatus.COUNTER_OFFER
        return ClientStatus.APPROVED
    return _BY_STATUS[status]
