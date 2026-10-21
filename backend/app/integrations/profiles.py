"""Синтетическая «правда» о компании, из которой моки внешних источников строят свои ответы.

Профиль детерминирован по ИНН: один и тот же ИНН всегда даёт ту же компанию, а ЕГРЮЛ, ФНС,
БКИ, ФССП и обороты РКО согласованы между собой. Демо-ИНН из DEMO_PROFILES включают
конкретные сценарии кредитной политики (стоп-факторы, эскалация, контр-предложения).
"""

import hashlib
import random
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from app.models.enums import CheckSource, LegalForm


@dataclass(frozen=True)
class Founder:
    full_name: str
    inn: str
    share_percent: Decimal
    is_beneficiary: bool = True
    sanctions_match: bool = False


@dataclass(frozen=True)
class Loan:
    creditor: str
    balance: Decimal
    monthly_payment: Decimal
    overdue_days: int = 0


@dataclass(frozen=True)
class Proceeding:
    number: str
    subject: str
    amount: Decimal
    opened_at: date


@dataclass(frozen=True)
class CompanyProfile:
    inn: str
    legal_form: LegalForm
    name: str
    ogrn: str
    kpp: str | None
    okved_main: str
    okved_name: str
    region: str
    legal_address: str
    registration_date: date
    director_name: str
    founders: tuple[Founder, ...]
    # ЕГРЮЛ: active | bankruptcy
    status: str = "active"
    # ФНС
    annual_revenue: Decimal = Decimal("0")
    taxes_paid: Decimal = Decimal("0")
    tax_debt: Decimal = Decimal("0")
    average_headcount: int = 0
    blocked_115fz: bool = False
    blocked_by_tax: bool = False
    mass_address: bool = False
    mass_director: bool = False
    # БКИ: скоринговый балл по шкале 1-999
    bki_score: int = 750
    loans: tuple[Loan, ...] = ()
    overdue_30_plus_12m: int = 0
    max_overdue_days_24m: int = 0
    inquiries_30d: int = 0
    refusals_90d: int = 0
    # ФССП
    proceedings: tuple[Proceeding, ...] = ()
    # Обороты РКО за 12 полных месяцев, от старого к новому: (поступления, списания)
    turnover: tuple[tuple[Decimal, Decimal], ...] = ()
    # Источники, которые в этом сценарии «не отвечают»
    unavailable: frozenset[CheckSource] = field(default_factory=frozenset)


class CompanyNotFoundError(Exception):
    pass


_LAST_NAMES = ("Иванов", "Смирнов", "Кузнецов", "Попов", "Соколов", "Лебедев", "Козлов", "Новиков")
_FIRST_NAMES = ("Алексей", "Сергей", "Дмитрий", "Андрей", "Михаил", "Николай", "Павел", "Игорь")
_PATRONYMICS = ("Иванович", "Петрович", "Сергеевич", "Андреевич", "Олегович", "Викторович")
_NAME_WORDS = ("Вектор", "Альфа Трейд", "Северный ветер", "Горизонт", "Стройресурс", "Агроинвест")
_OKVEDS = (
    ("47.11", "Торговля розничная в неспециализированных магазинах"),
    ("46.90", "Торговля оптовая неспециализированная"),
    ("41.20", "Строительство жилых и нежилых зданий"),
    ("49.41", "Деятельность автомобильного грузового транспорта"),
    ("56.10", "Деятельность ресторанов и услуги по доставке продуктов питания"),
    ("62.01", "Разработка компьютерного программного обеспечения"),
)
_REGIONS = (
    ("Москва", "г. Москва, ул. Тверская, д. {n}"),
    ("Санкт-Петербург", "г. Санкт-Петербург, Невский пр-т, д. {n}"),
    ("Новосибирская область", "г. Новосибирск, Красный пр-т, д. {n}"),
    ("Свердловская область", "г. Екатеринбург, ул. Ленина, д. {n}"),
    ("Республика Татарстан", "г. Казань, ул. Баумана, д. {n}"),
)
_BANKS = ("ПАО Сбербанк", "Банк ВТБ (ПАО)", "АО «Т-Банк»", "ПАО «Совкомбанк»")


def _rng(inn: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256(inn.encode()).digest()[:8], "big"))


def _money(value: float) -> Decimal:
    return Decimal(round(value / 1000) * 1000)


def _person(rng: random.Random) -> str:
    return f"{rng.choice(_LAST_NAMES)} {rng.choice(_FIRST_NAMES)} {rng.choice(_PATRONYMICS)}"


def _months_ago(today: date, months: int) -> date:
    total = today.year * 12 + today.month - 1 - months
    return date(total // 12, total % 12 + 1, min(today.day, 28))


def _annuity(balance: Decimal, months: int, rate: float = 0.18) -> Decimal:
    r = rate / 12
    return _money(float(balance) * r / (1 - (1 + r) ** -months))


def make_turnover(
    rng: random.Random,
    annual_revenue: Decimal,
    *,
    trend: float = 0.0,
    negative_streak: int = 0,
) -> tuple[tuple[Decimal, Decimal], ...]:
    """12 месяцев оборотов. trend - изменение последних 6 месяцев к предыдущим (-0.25 = падение
    на 25%); negative_streak - сколько последних месяцев подряд списания больше поступлений."""
    base = float(annual_revenue) / 12 / (1 + trend / 2)
    months = []
    for i in range(12):
        inflow = base * (1 + trend if i >= 6 else 1) * rng.uniform(0.95, 1.05)
        outflow = inflow * rng.uniform(0.85, 0.95)
        if i >= 12 - negative_streak:
            outflow = inflow * rng.uniform(1.1, 1.2)
        months.append((_money(inflow), _money(outflow)))
    return tuple(months)


def _ogrn(rng: random.Random, is_ip: bool) -> str:
    """ОГРН - 13 цифр, ОГРНИП - 15; контрольная цифра не моделируется."""
    digits = 14 if is_ip else 12
    return f"{3 if is_ip else 1}{rng.randrange(10**digits):0{digits}d}"


def generate_profile(inn: str, today: date) -> CompanyProfile:
    """Здоровая компания со случайными, но стабильными для ИНН параметрами."""
    rng = _rng(inn)
    is_ip = len(inn) == 12
    director = _person(rng)
    okved, okved_name = rng.choice(_OKVEDS)
    region, address = rng.choice(_REGIONS)
    revenue = _money(rng.uniform(15_000_000, 90_000_000))
    loan_balance = _money(float(revenue) * rng.uniform(0.02, 0.08))

    if is_ip:
        name = f"ИП {director}"
        founders = (Founder(director, inn, Decimal("100")),)
    else:
        name = f"ООО «{rng.choice(_NAME_WORDS)}»"
        partner = _person(rng)
        founders = (
            Founder(director, f"77{rng.randrange(10**10):010d}", Decimal("60")),
            Founder(partner, f"77{rng.randrange(10**10):010d}", Decimal("40")),
        )
    return CompanyProfile(
        inn=inn,
        legal_form=LegalForm.IP if is_ip else LegalForm.OOO,
        name=name,
        ogrn=_ogrn(rng, is_ip),
        kpp=None if is_ip else f"{inn[:4]}01001",
        okved_main=okved,
        okved_name=okved_name,
        region=region,
        legal_address=address.format(n=rng.randint(1, 120)),
        registration_date=_months_ago(today, rng.randint(30, 140)),
        director_name=director,
        founders=founders,
        annual_revenue=revenue,
        taxes_paid=_money(float(revenue) * rng.uniform(0.04, 0.07)),
        average_headcount=rng.randint(5, 60),
        bki_score=rng.randint(680, 880),
        loans=(Loan(rng.choice(_BANKS), loan_balance, _annuity(loan_balance, 36)),),
        inquiries_30d=rng.randint(0, 2),
        turnover=make_turnover(rng, revenue),
    )


# ИНН демо-сценариев: что меняется относительно здоровой компании
DEMO_SCENARIOS: dict[str, str] = {
    "7701000001": "Здоровая компания, зелёная зона",
    "7701000002": "Банкротство: стоп-фактор",
    "7701000003": "Счета заблокированы по 115-ФЗ: стоп-фактор",
    "7701000004": "Учредитель в санкционном списке: стоп-фактор",
    "7701000005": "Массовый адрес и массовый директор: стоп-фактор",
    "7701000006": "Нет сотрудников и налоговой активности: стоп-фактор",
    "7701000007": "Отрицательный Cash Flow 4 месяца подряд: стоп-фактор",
    "7701000008": "Бизнесу 7 месяцев: эскалация аналитику",
    "7701000009": "Слабая кредитная история: эскалация и риск-надбавка",
    "7701000010": "Падение выручки на 25%: риск-надбавка",
    "7701000011": "БКИ не отвечает",
    "7701000012": "Запрещённая деятельность (азартные игры): стоп-фактор",
    "7701000013": "Крупный действующий кредит: высокая долговая нагрузка",
    "7701000014": "Налоговая задолженность и исполнительные производства",
    "7701000099": "Компании нет в ЕГРЮЛ",
    "770100000001": "ИП, здоровый бизнес",
}


def _demo(base: CompanyProfile, today: date) -> CompanyProfile:
    rng = _rng(base.inn + "demo")
    match base.inn:
        case "7701000002":
            return replace(base, status="bankruptcy")
        case "7701000003":
            return replace(base, blocked_115fz=True)
        case "7701000004":
            founders = (replace(base.founders[0], sanctions_match=True), *base.founders[1:])
            return replace(base, founders=founders)
        case "7701000005":
            return replace(base, mass_address=True, mass_director=True)
        case "7701000006":
            return replace(base, average_headcount=0, taxes_paid=Decimal("0"))
        case "7701000007":
            return replace(
                base, turnover=make_turnover(rng, base.annual_revenue, negative_streak=4)
            )
        case "7701000008":
            return replace(base, registration_date=_months_ago(today, 7), loans=())
        case "7701000009":
            return replace(
                base, bki_score=540, overdue_30_plus_12m=2, max_overdue_days_24m=45, refusals_90d=3
            )
        case "7701000010":
            return replace(base, turnover=make_turnover(rng, base.annual_revenue, trend=-0.25))
        case "7701000011":
            return replace(base, unavailable=frozenset({CheckSource.BKI}))
        case "7701000012":
            return replace(base, okved_main="92.11", okved_name="Деятельность казино")
        case "7701000013":
            balance = _money(float(base.annual_revenue) * 0.25)
            loans = (Loan(_BANKS[0], balance, _annuity(balance, 24)),)
            return replace(base, loans=loans)
        case "7701000014":
            proceedings = (
                Proceeding(
                    "12345/26/77001-ИП",
                    "Задолженность по договору поставки",
                    Decimal("850000"),
                    _months_ago(today, 3),
                ),
                Proceeding("23456/26/77001-ИП", "Штраф", Decimal("40000"), _months_ago(today, 1)),
            )
            return replace(base, tax_debt=Decimal("320000"), proceedings=proceedings)
    return base


def get_profile(inn: str, today: date | None = None) -> CompanyProfile:
    today = today or date.today()
    if inn == "7701000099":
        raise CompanyNotFoundError(inn)
    return _demo(generate_profile(inn, today), today)
