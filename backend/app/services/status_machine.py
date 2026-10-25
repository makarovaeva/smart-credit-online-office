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
    (S.PRE_APPROVED, S.CLOSED): CLIENT,  # отказ после предварительного расчёта
    # Блок 02. Анализ ИИ
    # Порядок этапов по доске от 23.10: проверка -> скоринг -> маршрутизация -> (зелёная зона)
    # финансовый анализ и AI Credit Memo -> андеррайтер
    (S.SUBMITTED, S.AI_VERIFICATION): SYSTEM,
    (S.AI_VERIFICATION, S.AI_RISK_SCORING): SYSTEM,
    (S.AI_VERIFICATION, S.NEED_ADDITIONAL_DATA): SYSTEM,
    # Клиент ответил на дозапрос - заявка возвращается к инициатору: дозапрос ИИ - повторная
    # проверка комплекта, аналитика - к аналитику, андеррайтера - сразу повторное рассмотрение
    (S.NEED_ADDITIONAL_DATA, S.AI_VERIFICATION): CLIENT,
    (S.NEED_ADDITIONAL_DATA, S.ANALYST_ESCALATION): CLIENT,
    (S.NEED_ADDITIONAL_DATA, S.UNDERWRITER_REVIEW): CLIENT,
    (S.AI_RISK_SCORING, S.NEED_ADDITIONAL_DATA): SYSTEM,
    (S.AI_RISK_SCORING, S.DECISION_ROUTING): SYSTEM,
    # Блок 03. Маршрутизация: зелёная зона - финансовый анализ и андеррайтер,
    # жёлтая - аналитик, красная (стоп-фактор) - автоотказ
    (S.DECISION_ROUTING, S.AI_FINANCIAL_ANALYSIS): SYSTEM,
    (S.DECISION_ROUTING, S.ANALYST_ESCALATION): SYSTEM,
    (S.DECISION_ROUTING, S.CLOSED): SYSTEM,
    (S.AI_FINANCIAL_ANALYSIS, S.UNDERWRITER_REVIEW): SYSTEM,
    # Блок 04. Исключения
    (S.ANALYST_ESCALATION, S.ANALYST_COMPLETED): ANALYST,
    (S.ANALYST_ESCALATION, S.NEED_ADDITIONAL_DATA): ANALYST,  # запрос документов через ИИ
    (S.ANALYST_COMPLETED, S.UNDERWRITER_REVIEW): SYSTEM,
    # Блок 05. Решения андеррайтера
    (S.UNDERWRITER_REVIEW, S.OFFER_GENERATED): UNDERWRITER,  # approved / conditional_approval
    # more_information_required: документы у клиента или экспертиза аналитика
    (S.UNDERWRITER_REVIEW, S.NEED_ADDITIONAL_DATA): UNDERWRITER,
    (S.UNDERWRITER_REVIEW, S.ANALYST_ESCALATION): UNDERWRITER,
    (S.UNDERWRITER_REVIEW, S.CLOSED): UNDERWRITER,  # declined
    # Блок 06. Оффер
    (S.OFFER_GENERATED, S.OFFER_ACCEPTED): CLIENT,
    (S.OFFER_GENERATED, S.OFFER_REJECTED): CLIENT,
    (S.OFFER_REJECTED, S.CLOSED): SYSTEM,
    # Блок 07. Выдача (подписание и перечисление смоделированы)
    (S.OFFER_ACCEPTED, S.CONTRACT_GENERATION): SYSTEM,
    # Договор готовит система (CONTRACT_PREPARATION=auto) или кредитный аналитик
    (S.CONTRACT_GENERATION, S.E_SIGN): SYSTEM | ANALYST,
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
