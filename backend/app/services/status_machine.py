"""Допустимые переходы статуса заявки. Синхронизировано с docs/application-lifecycle.md."""

from app.models.enums import ActorType, ApplicationStatus

S = ApplicationStatus
CLIENT = frozenset({ActorType.CLIENT})
SYSTEM = frozenset({ActorType.SYSTEM})
ANALYST = frozenset({ActorType.CREDIT_ANALYST})
UNDERWRITER = frozenset({ActorType.UNDERWRITER})

# (из, в) -> кто может инициировать переход
TRANSITIONS: dict[tuple[ApplicationStatus, ApplicationStatus], frozenset[ActorType]] = {
    # Блок 01. Клиентский путь
    (S.DRAFT, S.DATA_COLLECTION): CLIENT,  # клиент дал согласия на получение данных
    (S.DATA_COLLECTION, S.PRE_APPROVED): SYSTEM,
    (S.PRE_APPROVED, S.SUBMITTED): CLIENT,
    # На доске финал этого отказа не определён - допущение: closed
    (S.PRE_APPROVED, S.CLOSED): CLIENT,
    # Блок 02. Анализ ИИ
    (S.SUBMITTED, S.AI_VERIFICATION): SYSTEM,
    (S.AI_VERIFICATION, S.AI_FINANCIAL_ANALYSIS): SYSTEM,
    (S.AI_VERIFICATION, S.NEED_ADDITIONAL_DATA): SYSTEM,
    (S.NEED_ADDITIONAL_DATA, S.AI_FINANCIAL_ANALYSIS): CLIENT,  # исправления получены
    (S.AI_FINANCIAL_ANALYSIS, S.AI_RISK_SCORING): SYSTEM,
    (S.AI_RISK_SCORING, S.NEED_ADDITIONAL_DATA): SYSTEM,
    (S.AI_RISK_SCORING, S.DECISION_ROUTING): SYSTEM,
    # Высокий fraud-риск - единственное автоматическое закрытие без андеррайтера
    (S.AI_VERIFICATION, S.CLOSED): SYSTEM,
    (S.AI_FINANCIAL_ANALYSIS, S.CLOSED): SYSTEM,
    (S.AI_RISK_SCORING, S.CLOSED): SYSTEM,
    # Блок 03. Маршрутизация: зелёная зона - андеррайтеру, жёлтая/красная - аналитику
    (S.DECISION_ROUTING, S.UNDERWRITER_REVIEW): SYSTEM,
    (S.DECISION_ROUTING, S.ANALYST_ESCALATION): SYSTEM,
    # Блок 04. Исключения
    (S.ANALYST_ESCALATION, S.ANALYST_COMPLETED): ANALYST,
    (S.ANALYST_COMPLETED, S.UNDERWRITER_REVIEW): SYSTEM,
    # Блок 05. Решения андеррайтера
    (S.UNDERWRITER_REVIEW, S.OFFER_GENERATED): UNDERWRITER,  # approved / conditional_approval
    (S.UNDERWRITER_REVIEW, S.NEED_ADDITIONAL_DATA): UNDERWRITER,  # more_information_required
    (S.UNDERWRITER_REVIEW, S.CLOSED): UNDERWRITER,  # declined
    # Блок 06. Оффер
    (S.OFFER_GENERATED, S.OFFER_ACCEPTED): CLIENT,
    (S.OFFER_GENERATED, S.OFFER_REJECTED): CLIENT,
    (S.OFFER_REJECTED, S.CLOSED): SYSTEM,
    # Блок 07. Выдача (подписание и перечисление смоделированы)
    (S.OFFER_ACCEPTED, S.CONTRACT_GENERATION): SYSTEM,
    (S.CONTRACT_GENERATION, S.E_SIGN): SYSTEM,
    (S.E_SIGN, S.DISBURSEMENT): CLIENT,
    (S.DISBURSEMENT, S.COMPLETED): SYSTEM,
}

FINAL_STATUSES = frozenset({S.COMPLETED, S.CLOSED})


class TransitionError(Exception):
    def __init__(self, current: ApplicationStatus, target: ApplicationStatus) -> None:
        super().__init__(f"transition {current} -> {target} is not allowed")
        self.current = current
        self.target = target


def can_transition(current: ApplicationStatus, target: ApplicationStatus, actor: ActorType) -> bool:
    return actor in TRANSITIONS.get((current, target), frozenset())


def ensure_transition(
    current: ApplicationStatus, target: ApplicationStatus, actor: ActorType
) -> None:
    if not can_transition(current, target, actor):
        raise TransitionError(current, target)
