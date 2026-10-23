"""Generate fictional Russian SME Borrower Profiles (MVP contract v0.1).

Usage, from ml/synthetic_data/:
    python company.py --count 1200 --seed 42 --mix population \
      --out data/profiles_generated.json

The generated identities are purely fictional. The demo is not an official
extract or a statistically calibrated sample of bank loan applicants.

Dependencies: numpy and the local financials.py module.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np

from financials import SCENARIO_NAMES, generate_financials, last_closed_month

# Joint counts from the Russian Federal Tax Service SME Register, 10 Sep 2026.
# "ЮЛ" here is approximated by ООО; other company legal forms are excluded
# from the MVP contract. These counts refer to the whole SME population,
# not to 24+-month-old bank loan applicants.
FNS_SEPT_2026_COUNTS = {
    ("micro", "ooo"): 1_800_777,
    ("micro", "ip"): 4_700_987,
    ("small", "ooo"): 204_779,
    ("small", "ip"): 36_500,
}

# Oversampling for functional tests, NOT an observed bank-applicant mix.
DEMO_WEIGHTS = {
    ("micro", "ooo"): 0.55,
    ("micro", "ip"): 0.20,
    ("small", "ooo"): 0.22,
    ("small", "ip"): 0.03,
}

# Illustrative industry coverage and weights (NOT taken from FNS statistics).
INDUSTRIES = (
    ("01.13", "Выращивание овощей", 0.08),
    ("10.71", "Производство хлеба и мучных изделий", 0.09),
    ("41.20", "Строительство жилых и нежилых зданий", 0.12),
    ("46.90", "Торговля оптовая неспециализированная", 0.18),
    ("47.11", "Торговля розничная преимущественно пищевыми продуктами", 0.22),
    ("56.10", "Деятельность ресторанов и услуги по доставке продуктов питания", 0.12),
    ("62.01", "Разработка компьютерного программного обеспечения", 0.19),
)

# Region weights are illustrative. This is not a countrywide representative map.
REGIONS = ("77", "78", "50", "23", "16", "66", "54", "61", "52", "63", "74", "59")
REGION_WEIGHTS = (0.21, 0.14, 0.12, 0.09, 0.08, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.03)

NAMES = ("Иван", "Алексей", "Дмитрий", "Михаил", "Сергей", "Андрей", "Николай", "Павел")
SURNAMES = ("Иванов", "Петров", "Смирнов", "Кузнецов", "Соколов", "Попов", "Волков", "Морозов")
PATRONYMICS = ("Иванович", "Петрович", "Сергеевич", "Андреевич", "Михайлович")
WORDS = ("Вектор", "Спектр", "Орион", "Меридиан", "Горизонт", "Ладога", "Парус", "Атлас")

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _ulid(at: date, rng: np.random.Generator) -> str:
    """Generate a real 26-character Crockford Base32 ULID, deterministic by seed."""
    timestamp = datetime(at.year, at.month, at.day, 12, tzinfo=timezone.utc)
    milliseconds = int(timestamp.timestamp() * 1000)
    value = (milliseconds << 80) | int.from_bytes(rng.bytes(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ULID_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def _digits(rng: np.random.Generator, count: int) -> str:
    return "".join(str(x) for x in rng.integers(0, 10, size=count))


def _weighted_checksum(digits: str, weights: tuple[int, ...]) -> str:
    return str(sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10)


def make_inn(legal_form: str, rng: np.random.Generator, region_code: str) -> str:
    """Generate a synthetic INN with valid check digits, not a real taxpayer."""
    if legal_form == "ooo":
        first9 = region_code + _digits(rng, 7)
        return first9 + _weighted_checksum(first9, (2, 4, 10, 3, 5, 9, 4, 6, 8))
    if legal_form == "ip":
        first10 = region_code + _digits(rng, 8)
        digit11 = _weighted_checksum(first10, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8))
        first11 = first10 + digit11
        return first11 + _weighted_checksum(first11, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8))
    raise ValueError("legal_form must be 'ooo' or 'ip'")


def make_ogrn(legal_form: str, rng: np.random.Generator,
              region_code: str, registration_year: int) -> str:
    """Generate synthetic OGRN/OGRNIP with a valid control digit."""
    if legal_form == "ooo":
        first12 = "1" + f"{registration_year % 100:02d}" + region_code + _digits(rng, 7)
        return first12 + str(int(first12) % 11 % 10)
    if legal_form == "ip":
        first14 = "3" + f"{registration_year % 100:02d}" + region_code + _digits(rng, 9)
        return first14 + str(int(first14) % 13 % 10)
    raise ValueError("legal_form must be 'ooo' or 'ip'")


def _subtract_months_first_day(last_year: int, last_month: int, months: int) -> date:
    serial = last_year * 12 + last_month - 1 - months
    return date(serial // 12, serial % 12 + 1, 1)


def _person(rng: np.random.Generator) -> str:
    return (f"{rng.choice(SURNAMES)} {rng.choice(NAMES)} "
            f"{rng.choice(PATRONYMICS)}")


def _pick_segment(mix: str, rng: np.random.Generator) -> tuple[str, str]:
    if mix == "population":
        weights = FNS_SEPT_2026_COUNTS
    elif mix == "demo":
        weights = DEMO_WEIGHTS
    else:
        raise ValueError("mix must be 'population' or 'demo'")
    labels = list(weights)
    probabilities = np.array([weights[label] for label in labels], dtype=float)
    probabilities /= probabilities.sum()
    return labels[int(rng.choice(len(labels), p=probabilities))]


def _employees(category: str, legal_form: str, rng: np.random.Generator,
               scenario: str = "baseline") -> int:
    """Illustrative counts conditional on segment (not estimated from official microdata)."""
    if category == "micro":
        zero_prob = 0.42 if legal_form == "ip" else (0.12 if scenario == "legacy_v01" else 0.0)
        if rng.random() < zero_prob:
            return 0
        # Shifted geometric: many firms with 1-3 employees; tail up to 15.
        return min(15, int(rng.geometric(p=0.34)))
    # Simplification: use 16-100 employees for every small firm. Small firms
    # can in reality have <=15 employees based on their income criteria.
    return min(100, 16 + int(rng.lognormal(mean=2.2, sigma=0.8)))


def _generate_one(index: int, rng: np.random.Generator,
                  as_of: date, last_period: date, mix: str,
                  scenario: str) -> tuple[dict, str]:
    category, legal_form = _pick_segment(mix, rng)
    region = str(rng.choice(REGIONS, p=REGION_WEIGHTS))
    industry_code, industry_name, _ = INDUSTRIES[int(rng.choice(
        len(INDUSTRIES), p=[industry[2] for industry in INDUSTRIES]
    ))]
    employees = _employees(category, legal_form, rng, scenario)

    # Require >=24 full months for the existing financials.py (young firms
    # intentionally excluded until the financial-data contract supports nulls).
    age_months = min(240, 25 + int(rng.gamma(shape=2.0, scale=30.0)))
    registration_month = _subtract_months_first_day(
        last_period.year, last_period.month, age_months
    )
    registration = registration_month.replace(day=int(rng.integers(1, 29)))
    reg_str = registration.isoformat()
    head_name = _person(rng)
    personal_inn = make_inn("ip", rng, region)
    birth_year = registration.year - int(rng.integers(22, 55))
    dob = date(birth_year, int(rng.integers(1, 13)), 14)
    birthday = dob.isoformat()
    borrower_id = f"brw_{_ulid(as_of, rng)}"
    short_label = f"{str(rng.choice(WORDS))}-{index:06d}"

    if legal_form == "ooo":
        full_name = f"Общество с ограниченной ответственностью «{short_label}»"
        short_name = f"ООО «{short_label}»"
        position = "Генеральный директор"
        company_inn = make_inn("ooo", rng, region)
        kpp = region + "01" + _digits(rng, 5)
    else:
        full_name = f"Индивидуальный предприниматель {head_name}"
        short_name = f"ИП {head_name}"
        position = "Индивидуальный предприниматель"
        company_inn = personal_inn
        kpp = None
    ogrn = make_ogrn(legal_form, rng, region, registration.year)
    ownership_first = 100.0 if legal_form == "ip" or rng.random() < 0.75 else 70.0
    owners = [{
        "owner_id": f"own_{_ulid(as_of, rng)}", "owner_type": "individual",
        "name": head_name, "inn": personal_inn,
        "ownership_share_pct": ownership_first,
        "is_beneficiary": True, "has_signing_authority": True,
    }]
    if ownership_first != 100:
        owners.append({
            "owner_id": f"own_{_ulid(as_of, rng)}", "owner_type": "individual",
            "name": _person(rng), "inn": make_inn("ip", rng, region),
            "ownership_share_pct": 30.0,
            "is_beneficiary": True, "has_signing_authority": False,
        })
    # Empty or zero-valued external-source blocks are intentionally neutral
    # placeholders, NOT realistic FNS, compliance, or credit-bureau samples.
    at = f"{as_of.isoformat()}T12:00:00Z"
    account_open = min(as_of, registration + timedelta(days=int(rng.integers(15, 181))))
    tax_system = str(rng.choice(
        ("usn_income", "usn_income_expense", "osno"),
        p=(0.40, 0.45, 0.15),
    ))
    annual_ceiling = 120_000_000 if category == "micro" else 800_000_000
    for _ in range(100):
        financials = generate_financials(
            employees_count=employees,
            okved_code=industry_code,
            registration_date=registration,
            as_of_date=as_of,
            rng=rng,
            source="documents" if legal_form == "ooo" else "bank_statements",
            scenario=scenario,
        )
        # Modeling shortcut: turnover used as proxy for tax income. Real
        # classification also depends on income and ownership; not equivalent.
        if financials["annual_turnover"] <= annual_ceiling:
            break
    else:
        raise RuntimeError("Could not draw a turnover within SME segment limits")

    profile = {
        "borrower_id": borrower_id,
        "status": "active",
        "customer_since": account_open.isoformat(),
        "company": {
            "legal_form": legal_form,
            "full_name": full_name,
            "short_name": short_name,
            "inn": company_inn,
            "kpp": kpp,
            "ogrn": ogrn,
            "registration_date": reg_str,
            "legal_address": f"[Вымышленный адрес] регион {region}, дом {index}",
            "actual_address": f"[Вымышленный адрес] регион {region}, дом {index}",
            "okved_main": {"code": industry_code, "name": industry_name},
            "tax_system": tax_system,
            "employees_count": employees,
            "region_code": region,
        },
        "head": {
            "full_name": head_name, "position": position,
            "inn_individual": personal_inn, "birth_date": birthday,
            "in_position_since": reg_str, "has_signing_authority": True,
        },
        "owners": owners,
        "contacts": {
            "phone": f"+7999{index:07d}",
            "email": f"synthetic-{index:06d}@example.invalid",
            "contact_person": {
                "full_name": head_name, "position": position,
                "phone": f"+7999{index:07d}",
            },
        },
        "fns_data": {
            "retrieved_at": at, "egrul_status": "active",
            "bankruptcy_status": "none", "has_account_block_115fz": False,
            "is_mass_address": False, "is_mass_director": False,
            "has_tax_activity": True, "tax_arrears_amount": 0,
        },
        "compliance": {
            "checked_at": at, "source": "internal_screening",
            "sanctions_hit": False, "is_prohibited_activity": False,
        },
        "bki_data": {
            "retrieved_at": at, "bureau": "synthetic_placeholder",
            "credit_history_quality": "none", "active_loans_count": 0,
            "total_debt_amount": 0, "monthly_debt_service": 0,
            "overdue_amount": 0, "max_overdue_days_12m": 0,
        },
        "financials": financials,
        "bank_account": {
            "account_number": ("40702" if legal_form == "ooo" else "40802")
                              + "810" + f"{index:012d}",
            "bik": "04" + _digits(rng, 7),
            "bank_name": "Учебный банк (вымышленный)", "currency": "RUB",
            "opened_at": account_open.isoformat(), "status": "active",
        },
        "documents": [],
        "created_at": at, "updated_at": at,
    }
    return profile, category


def generate_profiles(count: int, *, seed: int = 42,
                      as_of_date: date = date(2026, 9, 30),
                      mix: str = "population",
                      scenario: str = "baseline") -> tuple[list[dict], dict]:
    """Return (complete synthetic profiles, generation metadata)."""
    if type(count) is not int or not 1 <= count <= 100_000:
        raise ValueError("count must be an integer between 1 and 100000")
    if mix not in {"population", "demo"}:
        raise ValueError("mix must be 'population' or 'demo'")
    if scenario not in SCENARIO_NAMES:
        raise ValueError(f"Unknown scenario: {scenario}")
    if not isinstance(as_of_date, date):
        raise TypeError("as_of_date must be date")
    closed_year, closed_month = last_closed_month(as_of_date)
    last_period = date(closed_year, closed_month, 1)
    if last_period.year < 2007:
        raise ValueError("as_of_date is too early for the synthetic registration model")

    rng = np.random.default_rng(seed)
    result: list[dict] = []
    counts: Counter[str] = Counter()
    for index in range(1, count + 1):
        profile, category = _generate_one(index, rng, as_of_date, last_period, mix, scenario)
        result.append(profile)
        counts[f"{category}/{profile['company']['legal_form']}"] += 1
    turnovers = np.asarray([p["financials"]["annual_turnover"] for p in result], dtype=float)
    ebitdas = np.asarray([p["financials"]["ebitda"] for p in result], dtype=float)
    cash_runs_4plus = sum(
        any(all(value < 0 for value in flows[i:i + 4]) for i in range(9))
        for flows in (p["financials"]["cash_flow_last_12m"] for p in result)
    )
    metadata = {
        "seed": seed,
        "as_of_date": as_of_date.isoformat(),
        "mix": mix,
        "financial_scenario": scenario,
        "count": count,
        "by_segment": dict(sorted(counts.items())),
        "diagnostics": {
            "declining_revenue_share": round(float(np.mean(np.asarray(
                [p["financials"]["revenue_change_pct"] for p in result]) < 0)), 4),
            "zero_employees_ooo_share": round(sum(
                p["company"]["employees_count"] == 0 and p["company"]["legal_form"] == "ooo"
                for p in result
            ) / max(1, sum(p["company"]["legal_form"] == "ooo" for p in result)), 4),
            "median_turnover_rub": int(np.median(turnovers)),
            "turnover_p90_rub": int(np.quantile(turnovers, 0.90)),
            "negative_ebitda_share": round(float(np.mean(ebitdas < 0)), 4),
            "four_consecutive_negative_cf_months_share": round(cash_runs_4plus / count, 4),
        },
        "limitations": [
            "Only seven illustrative OKVED industries and twelve regions",
            "At least 24 full operating months; young businesses excluded",
            "FNS/compliance/BKI blocks are zero/clean placeholders, not sampled",
            "All legal entities approximated by OOO",
            "Tax income is approximated by annual turnover for segment caps",
            "No borrower default labels or credit decisions are generated",
        ],
    }
    return result, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic Borrower Profiles")
    parser.add_argument("--count", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--mix", choices=("population", "demo"), default="population")
    parser.add_argument("--scenario", choices=SCENARIO_NAMES, default="baseline")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()
    profiles, metadata = generate_profiles(
        args.count, seed=args.seed, as_of_date=args.as_of, mix=args.mix,
        scenario=args.scenario,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"Generated {len(profiles)} profiles -> {args.out}")
    print("Segments:", metadata["by_segment"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
