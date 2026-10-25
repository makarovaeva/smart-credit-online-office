"""Запасной генератор профилей заёмщиков (формат Borrower Profile) - для ИНН вне датасета.

Профиль детерминирован по ИНН. Демо-ИНН из DEMO_SCENARIOS включают сценарии кредитной политики.
"""

import hashlib
import random
from datetime import date
from typing import Any

from app.integrations.dataset import BorrowerProfile
from app.models.enums import CheckSource

NOT_FOUND_INNS = frozenset({"7701000099"})
# Источник «не отвечает» - проверка сохраняется со статусом failed
DEMO_UNAVAILABLE: dict[str, frozenset[CheckSource]] = {"7701000011": frozenset({CheckSource.BKI})}

DEMO_SCENARIOS: dict[str, str] = {
    "7701000001": "Здоровая компания, зелёная зона",
    "7701000002": "Действующее банкротство: стоп-фактор",
    "7701000003": "Запрещённая деятельность (азартные игры): стоп-фактор",
    "7701000004": "Нет сотрудников: стоп-фактор",
    "7701000005": "Нет налоговой активности: стоп-фактор",
    "7701000006": "Платежи по кредитам больше EBITDA: DSCR ниже 0,9, стоп-фактор",
    "7701000007": "Бизнесу 7 месяцев: эскалация аналитику",
    "7701000008": "Просрочка в БКИ: слабая кредитная история, эскалация и риск-надбавка",
    "7701000009": "Счёт заблокирован по 115-ФЗ: стоп-фактор",
    "7701000010": "Высокая действующая долговая нагрузка",
    "7701000011": "БКИ не отвечает",
    "7701000012": "Налоговая задолженность",
    "7701000013": "Собственник в санкционных списках: стоп-фактор",
    "7701000014": "Массовый адрес и массовый директор: стоп-фактор",
    "7701000015": "Отрицательный Cash Flow 4 месяца подряд: стоп-фактор",
    "7701000016": "Падение выручки на 25%: риск-надбавка",
    "7701000017": "Процедура наблюдения: стоп-фактор",
    "7701000018": "Пограничный риск: на 5 млн и 24 мес. не проходит, на большем сроке - проходит",
    "7701000019": "Счёт в другом банке: ИИ запрашивает выписку за 12 месяцев",
    "7701000099": "Компании нет в ЕГРЮЛ",
    "770100000001": "ИП, здоровый бизнес",
}

_LAST_NAMES = ("Иванов", "Смирнов", "Кузнецов", "Попов", "Соколов", "Лебедев", "Козлов", "Новиков")
_FIRST_NAMES = ("Алексей", "Сергей", "Дмитрий", "Андрей", "Михаил", "Николай", "Павел", "Игорь")
_PATRONYMICS = ("Иванович", "Петрович", "Сергеевич", "Андреевич", "Олегович", "Викторович")
_NAME_WORDS = ("Вектор", "Альфа Технологии", "Северный ветер", "Горизонт", "Стройресурс")
_OKVEDS = (
    ("47.11", "Торговля розничная в неспециализированных магазинах"),
    ("46.90", "Торговля оптовая неспециализированная"),
    ("41.20", "Строительство жилых и нежилых зданий"),
    ("49.41", "Деятельность автомобильного грузового транспорта"),
    ("56.10", "Деятельность ресторанов и услуги по доставке продуктов питания"),
    ("62.01", "Разработка компьютерного программного обеспечения"),
)
_REGIONS = (
    ("77", "г. Москва, ул. Тверская, д. {n}"),
    ("78", "г. Санкт-Петербург, Невский пр-т, д. {n}"),
    ("54", "г. Новосибирск, Красный пр-т, д. {n}"),
    ("66", "г. Екатеринбург, ул. Ленина, д. {n}"),
    ("16", "г. Казань, ул. Баумана, д. {n}"),
)
_TAX_SYSTEMS = ("usn_income", "usn_income_expense", "osno")
# Аннуитет на 36 месяцев под 18%: ежемесячный платёж ~3,6% остатка
_MONTHLY_PAYMENT_SHARE = 0.0362


def _rng(inn: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256(inn.encode()).digest()[:8], "big"))


def _rub(value: float) -> int:
    return round(value / 1000) * 1000


def _months_ago(today: date, months: int) -> date:
    total = today.year * 12 + today.month - 1 - months
    return date(total // 12, total % 12 + 1, min(today.day, 28))


def _person(rng: random.Random) -> str:
    return f"{rng.choice(_LAST_NAMES)} {rng.choice(_FIRST_NAMES)} {rng.choice(_PATRONYMICS)}"


def _healthy(inn: str, today: date) -> dict[str, Any]:
    rng = _rng(inn)
    is_ip = len(inn) == 12
    head = _person(rng)
    okved, okved_name = rng.choice(_OKVEDS)
    region_code, address = rng.choice(_REGIONS)
    registered = _months_ago(today, rng.randint(30, 140))
    retrieved = f"{today.isoformat()}T10:00:00Z"

    turnover = _rub(rng.uniform(15_000_000, 90_000_000))
    ebitda = _rub(turnover * rng.uniform(0.12, 0.20))
    total_debt = _rub(turnover * rng.uniform(0.02, 0.08))
    monthly_cash_flow = [_rub(ebitda / 12 * rng.uniform(0.6, 1.2)) for _ in range(12)]

    if is_ip:
        full_name, short_name = f"Индивидуальный предприниматель {head}", f"ИП {head}"
        owners = [
            {
                "owner_type": "individual",
                "name": head,
                "inn": inn,
                "ownership_share_pct": 100,
                "is_beneficiary": True,
                "has_signing_authority": True,
            }
        ]
    else:
        word = rng.choice(_NAME_WORDS)
        full_name = f"Общество с ограниченной ответственностью «{word}»"
        short_name = f"ООО «{word}»"
        partner = _person(rng)
        owners = [
            {
                "owner_type": "individual",
                "name": head,
                "inn": f"77{rng.randrange(10**10):010d}",
                "ownership_share_pct": 60,
                "is_beneficiary": True,
                "has_signing_authority": True,
            },
            {
                "owner_type": "individual",
                "name": partner,
                "inn": f"77{rng.randrange(10**10):010d}",
                "ownership_share_pct": 40,
                "is_beneficiary": True,
                "has_signing_authority": False,
            },
        ]
    legal_address = address.format(n=rng.randint(1, 120))
    return {
        "borrower_id": f"brw_{inn}",
        "status": "active",
        "customer_since": registered.isoformat(),
        "company": {
            "legal_form": "ip" if is_ip else "ooo",
            "full_name": full_name,
            "short_name": short_name,
            "inn": inn,
            "kpp": None if is_ip else f"{inn[:4]}01001",
            "ogrn": f"3{rng.randrange(10**14):014d}" if is_ip else f"1{rng.randrange(10**12):012d}",
            "registration_date": registered.isoformat(),
            "legal_address": legal_address,
            "actual_address": legal_address,
            "okved_main": {"code": okved, "name": okved_name},
            "tax_system": rng.choice(_TAX_SYSTEMS),
            "employees_count": rng.randint(5, 60),
            "region_code": region_code,
        },
        "head": {
            "full_name": head,
            "position": "Индивидуальный предприниматель" if is_ip else "Генеральный директор",
            "in_position_since": registered.isoformat(),
            "has_signing_authority": True,
        },
        "owners": owners,
        "contacts": {"phone": None, "email": f"finance@{inn}.example"},
        "fns_data": {
            "retrieved_at": retrieved,
            "egrul_status": "active",
            "bankruptcy_status": "none",
            "has_account_block_115fz": False,
            "is_mass_address": False,
            "is_mass_director": False,
            "has_tax_activity": True,
            "tax_arrears_amount": 0,
        },
        "compliance": {
            "checked_at": retrieved,
            "source": "internal_screening",
            "sanctions_hit": False,
            "is_prohibited_activity": False,
        },
        "bki_data": {
            "retrieved_at": retrieved,
            "bureau": "НБКИ",
            "credit_history_quality": "good",
            "active_loans_count": rng.randint(1, 2),
            "total_debt_amount": total_debt,
            "monthly_debt_service": _rub(total_debt * _MONTHLY_PAYMENT_SHARE),
            "overdue_amount": 0,
            "max_overdue_days_12m": 0,
        },
        "financials": {
            "as_of_date": _months_ago(today, 1).isoformat(),
            "annual_turnover": turnover,
            "revenue_change_pct": round(rng.uniform(-8, 12), 1),
            "ebitda": ebitda,
            "cash_flow_last_12m": monthly_cash_flow,
            "source": "fns",
        },
        "bank_account": {
            "account_number": f"40702810{inn[-10:]}00",
            "bik": "044525593",
            "bank_name": "АО «Альфа-Банк»",
            "currency": "RUB",
            "status": "active",
        },
        "documents": [],
    }


def _apply_demo(p: dict[str, Any], today: date) -> None:
    company, fns, compliance, bki, fin = (
        p["company"],
        p["fns_data"],
        p["compliance"],
        p["bki_data"],
        p["financials"],
    )
    match company["inn"]:
        case "7701000002":
            fns["bankruptcy_status"] = "bankruptcy"
        case "7701000003":
            company["okved_main"] = {"code": "92.11", "name": "Деятельность казино"}
            compliance["is_prohibited_activity"] = True
        case "7701000004":
            company["employees_count"] = 0
        case "7701000005":
            fns["has_tax_activity"] = False
        case "7701000006":
            bki["monthly_debt_service"] = _rub(fin["ebitda"] * 1.25 / 12)
            bki["total_debt_amount"] = _rub(bki["monthly_debt_service"] / _MONTHLY_PAYMENT_SHARE)
        case "7701000007":
            registered = _months_ago(today, 7).isoformat()
            company["registration_date"] = p["head"]["in_position_since"] = registered
            bki.update(
                credit_history_quality="none",
                active_loans_count=0,
                total_debt_amount=0,
                monthly_debt_service=0,
            )
        case "7701000008":
            bki.update(
                credit_history_quality="weak", overdue_amount=250_000, max_overdue_days_12m=45
            )
        case "7701000009":
            fns["has_account_block_115fz"] = True
        case "7701000010":
            bki["total_debt_amount"] = _rub(fin["annual_turnover"] * 0.3)
            bki["monthly_debt_service"] = _rub(fin["ebitda"] * 0.55 / 12)
        case "7701000012":
            fns["tax_arrears_amount"] = 320_000
        case "7701000013":
            compliance["sanctions_hit"] = True
        case "7701000014":
            fns.update(is_mass_address=True, is_mass_director=True)
        case "7701000015":
            fin["cash_flow_last_12m"][-4:] = [-abs(v) for v in fin["cash_flow_last_12m"][-4:]]
        case "7701000016":
            fin["revenue_change_pct"] = -25.0
        case "7701000017":
            fns["bankruptcy_status"] = "observation"
        case "7701000018":
            # 5 млн на 24 мес. (срок по умолчанию в интерфейсе): DSCR ~0,97 - ниже 1,1,
            # но не стоп-фактор; на 29+ мес. проходит - контр-предложение продлением срока
            fin.update(annual_turnover=40_000_000, ebitda=3_200_000)
            bki.update(active_loans_count=1, total_debt_amount=690_000, monthly_debt_service=25_000)
        case "7701000019":
            p["bank_account"].update(
                account_number=f"40702810{company['inn'][-10:]}77",
                bik="044525999",
                bank_name="АО «Банк Пример»",
            )


def generate_profile(inn: str, today: date) -> BorrowerProfile:
    profile = _healthy(inn, today)
    _apply_demo(profile, today)
    return BorrowerProfile.model_validate(profile)
