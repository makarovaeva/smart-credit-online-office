"""Импорт всех моделей, чтобы они попали в Base.metadata (нужно Alembic autogenerate)."""

from app.models.application import (
    Application,
    ApplicationConsent,
    ApplicationStatusHistory,
    PreApproval,
)
from app.models.assessment import CreditDecision, CreditMemo, ExternalCheck, ScoringResult
from app.models.chat import ChatMessage
from app.models.company import Company, CompanyMember, CompanyOwner
from app.models.document import Document, InfoRequest
from app.models.loan import LoanContract, PaymentScheduleItem
from app.models.notification import Notification
from app.models.product import CreditProduct
from app.models.user import User

__all__ = [
    "Application",
    "ApplicationConsent",
    "ApplicationStatusHistory",
    "ChatMessage",
    "Company",
    "CompanyMember",
    "CompanyOwner",
    "CreditDecision",
    "CreditMemo",
    "CreditProduct",
    "Document",
    "ExternalCheck",
    "InfoRequest",
    "LoanContract",
    "Notification",
    "PaymentScheduleItem",
    "PreApproval",
    "ScoringResult",
    "User",
]
