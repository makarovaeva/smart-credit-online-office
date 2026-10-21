"""Мок ЕГРЮЛ/ЕГРИП: реквизиты, статус юрлица, руководитель и учредители.

Совпадения с санкционными списками для простоты отдаются здесь же, у учредителей.
"""

from datetime import date
from typing import Any

from app.integrations.base import load_profile
from app.models.enums import CheckSource

STATUS_NAMES = {
    "active": "Действующее",
    "bankruptcy": "Процедура банкротства (наблюдение)",
}


async def fetch(inn: str, today: date | None = None) -> dict[str, Any]:
    p = load_profile(CheckSource.EGRUL, inn, today)
    return {
        "inn": p.inn,
        "ogrn": p.ogrn,
        "kpp": p.kpp,
        "legal_form": p.legal_form.value,
        "name": p.name,
        "okved_main": {"code": p.okved_main, "name": p.okved_name},
        "registration_date": p.registration_date.isoformat(),
        "region": p.region,
        "legal_address": p.legal_address,
        "status": {"code": p.status, "name": STATUS_NAMES[p.status]},
        "director": {"full_name": p.director_name},
        "founders": [
            {
                "full_name": f.full_name,
                "inn": f.inn,
                "share_percent": str(f.share_percent),
                "is_beneficiary": f.is_beneficiary,
                "sanctions_match": f.sanctions_match,
            }
            for f in p.founders
        ],
    }
