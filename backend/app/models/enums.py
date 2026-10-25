from enum import StrEnum


class UserRole(StrEnum):
    CLIENT = "client"
    CREDIT_ANALYST = "credit_analyst"
    UNDERWRITER = "underwriter"
    ADMIN = "admin"


class CompanyMemberRole(StrEnum):
    OWNER = "owner"
    DIRECTOR = "director"
    ACCOUNTANT = "accountant"
    FINANCE_MANAGER = "finance_manager"
    AUTHORIZED_EMPLOYEE = "authorized_employee"


class LegalForm(StrEnum):
    IP = "ip"
    OOO = "ooo"


class LoanPurpose(StrEnum):
    WORKING_CAPITAL = "working_capital"
    EQUIPMENT = "equipment"
    BUSINESS_EXPANSION = "business_expansion"
    REFINANCING = "refinancing"
    OTHER = "other"


class CreditFormat(StrEnum):
    LOAN = "loan"
    REVOLVING_CREDIT_LINE = "revolving_credit_line"
    NON_REVOLVING_CREDIT_LINE = "non_revolving_credit_line"
    OVERDRAFT = "overdraft"


class CollateralType(StrEnum):
    """Тип залога определяет дисконт к рыночной стоимости при расчёте LTV."""

    COMMERCIAL_REAL_ESTATE = "commercial_real_estate"
    RESIDENTIAL_REAL_ESTATE = "residential_real_estate"
    VEHICLE = "vehicle"
    EQUIPMENT = "equipment"
    INVENTORY = "inventory"


class ApplicationStatus(StrEnum):
    """18 этапов + 2 терминальных статуса из статусной модели на доске Figma."""

    DRAFT = "draft"
    DATA_COLLECTION = "data_collection"
    PRE_APPROVED = "pre_approved"
    SUBMITTED = "submitted"
    AI_VERIFICATION = "ai_verification"
    NEED_ADDITIONAL_DATA = "need_additional_data"
    AI_FINANCIAL_ANALYSIS = "ai_financial_analysis"
    AI_RISK_SCORING = "ai_risk_scoring"
    DECISION_ROUTING = "decision_routing"
    ANALYST_ESCALATION = "analyst_escalation"
    ANALYST_COMPLETED = "analyst_completed"
    UNDERWRITER_REVIEW = "underwriter_review"
    OFFER_GENERATED = "offer_generated"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_REJECTED = "offer_rejected"
    CONTRACT_GENERATION = "contract_generation"
    E_SIGN = "e_sign"
    DISBURSEMENT = "disbursement"
    COMPLETED = "completed"
    CLOSED = "closed"


class ActorType(StrEnum):
    CLIENT = "client"
    # ИИ-кредитный агент и прочая автоматика конвейера
    SYSTEM = "system"
    CREDIT_ANALYST = "credit_analyst"
    UNDERWRITER = "underwriter"


class ConsentType(StrEnum):
    BKI = "bki"
    FNS = "fns"
    DIGITAL_PROFILE = "digital_profile"


class DocumentType(StrEnum):
    BANK_STATEMENT = "bank_statement"
    TAX_RETURN = "tax_return"
    KUDIR = "kudir"
    FINANCIAL_STATEMENT = "financial_statement"
    MANAGEMENT_REPORT = "management_report"
    CONTRACT = "contract"
    # Залоговые документы - только для ветки с залогом
    EGRN_EXTRACT = "egrn_extract"
    VEHICLE_PASSPORT = "vehicle_passport"
    EQUIPMENT_DOCUMENTS = "equipment_documents"
    APPRAISAL_REPORT = "appraisal_report"
    CREDIT_AGREEMENT = "credit_agreement"
    OTHER = "other"


class DocumentStatus(StrEnum):
    """Проверка документа ИИ на этапе ai_verification (симуляция: формат проверен при загрузке)."""

    UPLOADED = "uploaded"
    VERIFIED = "verified"
    REJECTED = "rejected"


class InfoRequestStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    CANCELLED = "cancelled"


class CheckSource(StrEnum):
    EGRUL = "egrul"
    FNS = "fns"
    BKI = "bki"
    FSSP = "fssp"
    BANK_TURNOVER = "bank_turnover"
    DIGITAL_PROFILE = "digital_profile"
    # Санкционные списки и запрещённая деятельность
    COMPLIANCE = "compliance"


class CheckStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class RiskGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class RiskZone(StrEnum):
    """Зелёная - к андеррайтеру, жёлтая - к кредитному аналитику, красная - автоотказ."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class AiRecommendation(StrEnum):
    APPROVE = "approve"
    COUNTER_OFFER = "counter_offer"
    DECLINE = "decline"
    REQUEST_MORE_INFO = "request_more_info"


class DecisionType(StrEnum):
    """Четыре решения андеррайтера."""

    APPROVED = "approved"
    CONDITIONAL_APPROVAL = "conditional_approval"
    DECLINED = "declined"
    MORE_INFORMATION_REQUIRED = "more_information_required"


class MoreInfoTarget(StrEnum):
    """Кому андеррайтер адресует more_information_required."""

    # Документы у клиента: дозапрос формирует ИИ-агент
    CLIENT = "client"
    # Дополнительная экспертиза и обновление заключения
    CREDIT_ANALYST = "credit_analyst"


class OfferResponse(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CloseReason(StrEnum):
    """Пути к финалу «Закрыто без выдачи»: четыре с доски и отмена клиентом."""

    PRE_APPROVAL_DECLINED = "pre_approval_declined"
    AUTO_DECLINED = "auto_declined"
    UNDERWRITER_DECLINED = "underwriter_declined"
    OFFER_REJECTED = "offer_rejected"
    # Клиент отменил заявку до решения банка
    CLIENT_CANCELLED = "client_cancelled"


class StopFactorCode(StrEnum):
    """Стоп-факторы кредитной политики: любой из них - автоотказ."""

    # Юридические
    BANKRUPTCY = "bankruptcy"
    OBSERVATION_PROCEDURE = "observation_procedure"
    ACCOUNTS_BLOCKED_115FZ = "accounts_blocked_115fz"
    SANCTIONED_OWNER = "sanctioned_owner"
    PROHIBITED_ACTIVITY = "prohibited_activity"
    # Финансовые
    NEGATIVE_CASH_FLOW = "negative_cash_flow"
    LOW_DSCR = "low_dscr"
    # Признаки фиктивного бизнеса
    MASS_ADDRESS = "mass_address"
    MASS_DIRECTOR = "mass_director"
    NO_EMPLOYEES = "no_employees"
    NO_TAX_ACTIVITY = "no_tax_activity"


class StopFactorCategory(StrEnum):
    LEGAL = "legal"
    FINANCIAL = "financial"
    FICTITIOUS = "fictitious"


class EscalationReasonCode(StrEnum):
    """Основания передачи кредитному аналитику (жёлтая зона)."""

    LOW_CONFIDENCE = "low_confidence"
    YOUNG_BUSINESS = "young_business"
    CONFLICTING_DATA = "conflicting_data"
    HIGH_LTV = "high_ltv"
    WEAK_CREDIT_HISTORY = "weak_credit_history"
    # Допущения: на доске эти случаи не описаны
    SEVERE_REVENUE_DROP = "severe_revenue_drop"
    NO_COUNTER_OFFER = "no_counter_offer"
    MISSING_EXTERNAL_DATA = "missing_external_data"


class AlternativeOfferKind(StrEnum):
    """Альтернативные варианты условий при пограничном риске - каждый проходит зелёную зону."""

    # Сумма сохраняется, срок - минимальный проходящий
    LONGER_TERM = "longer_term"
    # Срок как в заявке, сумма - максимальная проходящая
    LOWER_AMOUNT = "lower_amount"
    # Максимальный срок продукта и наибольшая сумма на нём
    MAX_TERM = "max_term"


class CounterOfferScenario(StrEnum):
    """Сценарии контр-предложения ИИ из кредитной политики."""

    AUTO_APPROVAL_LIMIT = "auto_approval_limit"
    TERM_EXTENSION = "term_extension"
    # Больше не применяется: по доске от 23.10 Debt Burden только аналитический показатель.
    # Значение оставлено, чтобы читались ранее сохранённые Credit Memo
    DEBT_BURDEN_AMOUNT_REDUCTION = "debt_burden_amount_reduction"
    LTV_AMOUNT_REDUCTION = "ltv_amount_reduction"
    RISK_PREMIUM = "risk_premium"


class LoanContractStatus(StrEnum):
    """Статус кредитного договора (раздел «Кредиты»)."""

    AWAITING_SIGNATURE = "awaiting_signature"
    SIGNED = "signed"
    # Средства выданы, кредит обслуживается
    ACTIVE = "active"
    OVERDUE = "overdue"
    CLOSED = "closed"


class RepaymentType(StrEnum):
    ANNUITY = "annuity"
    DIFFERENTIATED = "differentiated"


class PaymentStatus(StrEnum):
    SCHEDULED = "scheduled"
    PAID = "paid"
    OVERDUE = "overdue"


class ChatSender(StrEnum):
    CLIENT = "client"
    AI_AGENT = "ai_agent"


class ChatMessageType(StrEnum):
    """Вид сообщения чата определяет отображение (формат Chat History из документа модели)."""

    TEXT = "text"
    # Карточка с параметрами заявки, которые агент разобрал из текста
    CONFIRMATION_CARD = "confirmation_card"
    DOCUMENT_REQUEST = "document_request"
    STATUS_NOTIFICATION = "status_notification"
    REJECTION_NOTICE = "rejection_notice"


class InternalRequestStatus(StrEnum):
    """Запрос экспертизы андеррайтера у аналитика."""

    OPEN = "open"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    # Аналитик вернул запрос андеррайтеру с комментарием, без заключения
    RETURNED = "returned"
    # Андеррайтер отозвал запрос
    CANCELLED = "cancelled"


class NotificationType(StrEnum):
    STATUS_CHANGED = "status_changed"
    DOCUMENT_REQUEST = "document_request"
    OFFER_READY = "offer_ready"
    CONTRACT_TO_SIGN = "contract_to_sign"
    FUNDS_DISBURSED = "funds_disbursed"
    APPLICATION_DECLINED = "application_declined"
    # Сотрудникам
    APPLICATION_ASSIGNED = "application_assigned"
    EXPERTISE_REQUEST = "expertise_request"
    REQUEST_RETURNED = "request_returned"
    REMINDER = "reminder"
