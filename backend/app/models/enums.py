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
    COLLATERAL = "collateral"
    CREDIT_AGREEMENT = "credit_agreement"
    OTHER = "other"


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
    """Зелёная - к андеррайтеру, жёлтая и красная - к кредитному аналитику."""

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


class OfferResponse(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
