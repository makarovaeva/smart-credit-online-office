"""Комплект документов, который ИИ проверяет на этапе ai_verification.

Данные о бизнесе банк получает из внешних источников, поэтому документы нужны, только если
источников не хватает:
- выписка по счёту за 12 месяцев - расчётный счёт не в банке (обороты не видны);
- бухгалтерская отчётность - ФНС не отдала финансовые показатели и их нет в анкете;
- документы на залог - по типу обеспечения.
"""

from dataclasses import dataclass

from app.models import Application
from app.models.enums import CollateralType, DocumentType

# Банк, в котором открыт счёт клиента, - по профилю заёмщика
HOME_BANK_MARKER = "Альфа-Банк"

COLLATERAL_DOCUMENTS = {
    CollateralType.COMMERCIAL_REAL_ESTATE: DocumentType.EGRN_EXTRACT,
    CollateralType.RESIDENTIAL_REAL_ESTATE: DocumentType.EGRN_EXTRACT,
    CollateralType.VEHICLE: DocumentType.VEHICLE_PASSPORT,
    CollateralType.EQUIPMENT: DocumentType.EQUIPMENT_DOCUMENTS,
}

DOCUMENT_NAMES = {
    DocumentType.BANK_STATEMENT: "выписка по расчётному счёту за 12 месяцев",
    DocumentType.TAX_RETURN: "налоговая декларация",
    DocumentType.KUDIR: "КУДИР",
    DocumentType.FINANCIAL_STATEMENT: "бухгалтерская отчётность за последний год",
    DocumentType.MANAGEMENT_REPORT: "управленческая отчётность",
    DocumentType.CONTRACT: "договор с контрагентом",
    DocumentType.EGRN_EXTRACT: "выписка из ЕГРН на объект залога",
    DocumentType.VEHICLE_PASSPORT: "ПТС транспортного средства",
    DocumentType.EQUIPMENT_DOCUMENTS: "документы на оборудование",
    DocumentType.APPRAISAL_REPORT: "отчёт об оценке залога",
    DocumentType.CREDIT_AGREEMENT: "кредитный договор",
    DocumentType.OTHER: "прочий документ",
}


@dataclass(frozen=True)
class Requirement:
    type: DocumentType
    reason: str


def required_documents(
    application: Application, bank_account: dict | None, has_financials: bool
) -> list[Requirement]:
    """has_financials - есть выручка и EBITDA (из ФНС или анкеты)."""
    required = []
    if not bank_account or HOME_BANK_MARKER not in str(bank_account.get("bank_name", "")):
        required.append(
            Requirement(DocumentType.BANK_STATEMENT, "расчётный счёт открыт в другом банке")
        )
    if not has_financials:
        required.append(
            Requirement(DocumentType.FINANCIAL_STATEMENT, "ФНС не вернула финансовые показатели")
        )
    if application.has_collateral and application.collateral_type in COLLATERAL_DOCUMENTS:
        required.append(
            Requirement(COLLATERAL_DOCUMENTS[application.collateral_type], "заявка с залогом")
        )
    return required


def request_message(missing: list[Requirement]) -> str:
    items = "; ".join(f"{DOCUMENT_NAMES[r.type]} ({r.reason})" for r in missing)
    return f"Для проверки заявки загрузите документы: {items}"
