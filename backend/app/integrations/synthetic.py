"""Запасной генератор записей в формате ML - для ИНН, которых нет в датасете.

Запись детерминирована по ИНН. Демо-ИНН из DEMO_SCENARIOS включают сценарии кредитной политики,
построенные только на полях формата ML.
"""

import hashlib
import random
from datetime import date
from typing import Any

from app.integrations.dataset import BorrowerRecord
from app.models.enums import CheckSource, LoanPurpose

NOT_FOUND_INNS = frozenset({"7701000099"})
# Источник «не отвечает» - проверка сохраняется со статусом failed
DEMO_UNAVAILABLE: dict[str, frozenset[CheckSource]] = {"7701000011": frozenset({CheckSource.BKI})}

DEMO_SCENARIOS: dict[str, str] = {
    "7701000001": "Здоровая компания, зелёная зона",
    "7701000002": "Компания недействующая (ФНС): стоп-фактор",
    "7701000003": "Запрещённая деятельность (азартные игры): стоп-фактор",
    "7701000004": "Нет сотрудников: стоп-фактор",
    "7701000005": "Нет доходов в ФНС: стоп-фактор «нет налоговой активности»",
    "7701000006": "Платежи по кредитам больше EBITDA: DSCR ниже 0,9, стоп-фактор",
    "7701000007": "Бизнесу 7 месяцев: эскалация аналитику",
    "7701000008": "Просрочка в БКИ: слабая кредитная история, эскалация",
    "7701000009": "Выручка в отчётности расходится с ФНС: конфликт данных, эскалация",
    "7701000010": "Высокая действующая долговая нагрузка",
    "7701000011": "БКИ не отвечает",
    "7701000012": "Налоговая задолженность",
    "7701000099": "Компании нет в ЕГРЮЛ",
    "770100000001": "ИП, здоровый бизнес",
}

_LAST_NAMES = ("Иванов", "Смирнов", "Кузнецов", "Попов", "Соколов", "Лебедев", "Козлов", "Новиков")
_FIRST_NAMES = ("Алексей", "Сергей", "Дмитрий", "Андрей", "Михаил", "Николай", "Павел", "Игорь")
_PATRONYMICS = ("Иванович", "Петрович", "Сергеевич", "Андреевич", "Олегович", "Викторович")
_NAME_WORDS = ("Вектор", "Альфа Технологии", "Северный ветер", "Горизонт", "Стройресурс")
_OKVEDS = ("47.11", "46.90", "41.20", "49.41", "56.10", "62.01")
_REGION_CODES = ("77", "78", "54", "66", "16")


def _rng(inn: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256(inn.encode()).digest()[:8], "big"))


def _rub(value: float) -> int:
    return round(value / 1000) * 1000


def _months_ago(today: date, months: int) -> date:
    total = today.year * 12 + today.month - 1 - months
    return date(total // 12, total % 12 + 1, min(today.day, 28))


def _sme_category(revenue: int, employees: int) -> str:
    if revenue <= 120_000_000 and employees <= 15:
        return "micro"
    if revenue <= 800_000_000 and employees <= 100:
        return "small"
    return "medium"


def _healthy(inn: str, today: date) -> dict[str, Any]:
    rng = _rng(inn)
    is_ip = len(inn) == 12
    person = f"{rng.choice(_LAST_NAMES)} {rng.choice(_FIRST_NAMES)} {rng.choice(_PATRONYMICS)}"
    registered = _months_ago(today, rng.randint(30, 140))
    employees = rng.randint(5, 60)

    revenue = _rub(rng.uniform(15_000_000, 90_000_000))
    operating_costs = _rub(revenue * rng.uniform(0.80, 0.88))
    ebitda = revenue - operating_costs
    total_debt = _rub(revenue * rng.uniform(0.02, 0.08))
    # Аннуитет на 36 месяцев под 18%: ~43% остатка в год
    debt_service = _rub(total_debt * 0.434)
    assets = _rub(revenue * rng.uniform(0.5, 0.9))
    liabilities = total_debt + _rub(revenue * rng.uniform(0.05, 0.15))
    return {
        "borrower_id": f"SYN-{inn}",
        "application_id": f"APP-{inn}",
        "as_of_date": today.isoformat(),
        "company": {
            "name": f"ИП {person}" if is_ip else f"ООО «{rng.choice(_NAME_WORDS)}»",
            "legal_form": "IP" if is_ip else "OOO",
            "inn": inn,
            "registration_number": (
                f"3{rng.randrange(10**14):014d}" if is_ip else f"1{rng.randrange(10**12):012d}"
            ),
            "okved_main": rng.choice(_OKVEDS),
            "region_code": rng.choice(_REGION_CODES),
            "registration_date": registered.isoformat(),
            "employees_count": employees,
        },
        "financials": {
            "report_year": today.year - 1,
            "revenue_rub": revenue,
            "operating_costs_rub": operating_costs,
            "ebitda_rub": ebitda,
            "cfads_rub": _rub(ebitda * rng.uniform(0.6, 0.75)),
            "total_debt_rub": total_debt,
            "annual_debt_service_rub": debt_service,
            "assets_rub": assets,
            "liabilities_rub": liabilities,
            "equity_rub": assets - liabilities,
        },
        "fns": {
            "is_active": True,
            "sme_category": _sme_category(revenue, employees),
            "annual_income_rub": revenue,
            "tax_debt_rub": 0,
        },
        "bki": {
            "active_loans": rng.randint(1, 2),
            "outstanding_debt_rub": total_debt,
            "overdue_debt_rub": 0,
            "max_overdue_days": 0,
            "credit_history_months": min(
                (today.year - registered.year) * 12 + today.month - registered.month,
                rng.randint(24, 100),
            ),
        },
        "loan_application": {
            "requested_amount_rub": _rub(revenue * rng.uniform(0.05, 0.12) / 100) * 100,
            "term_months": rng.choice((12, 24, 36, 48, 60)),
            "purpose": rng.choice([p.value for p in LoanPurpose]),
            "collateral_value_rub": None,
        },
    }


def _apply_demo(record: dict[str, Any], today: date) -> None:
    company, fin, fns, bki = (
        record["company"],
        record["financials"],
        record["fns"],
        record["bki"],
    )
    match company["inn"]:
        case "7701000002":
            fns["is_active"] = False
        case "7701000003":
            company["okved_main"] = "92.11"
        case "7701000004":
            company["employees_count"] = 0
        case "7701000005":
            fns["annual_income_rub"] = 0
        case "7701000006":
            fin["annual_debt_service_rub"] = _rub(fin["ebitda_rub"] * 1.25)
        case "7701000007":
            company["registration_date"] = _months_ago(today, 7).isoformat()
            fin["total_debt_rub"] = fin["annual_debt_service_rub"] = 0
            bki.update(active_loans=0, outstanding_debt_rub=0, credit_history_months=0)
        case "7701000008":
            bki.update(overdue_debt_rub=250_000, max_overdue_days=45)
        case "7701000009":
            fns["annual_income_rub"] = _rub(fin["revenue_rub"] * 0.6)
        case "7701000010":
            fin["total_debt_rub"] = bki["outstanding_debt_rub"] = _rub(fin["revenue_rub"] * 0.3)
            fin["annual_debt_service_rub"] = _rub(fin["ebitda_rub"] * 0.55)
        case "7701000012":
            fns["tax_debt_rub"] = 320_000


def generate_record(inn: str, today: date) -> BorrowerRecord:
    record = _healthy(inn, today)
    _apply_demo(record, today)
    return BorrowerRecord.model_validate(record)
