"""Обогащение заявки данными внешних источников по ИНН заёмщика."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import SOURCES, CompanyNotFoundError, SourceUnavailableError
from app.models import Application, Company, ExternalCheck
from app.models.enums import CheckSource, CheckStatus
from app.services.features import Features, build_features


async def _call(
    source: CheckSource, inn: str, today: date | None
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return await SOURCES[source](inn, today), None
    except SourceUnavailableError as e:
        return None, str(e)
    except CompanyNotFoundError:
        return None, f"ИНН {inn} не найден в {source}"


async def collect_external_data(
    session: AsyncSession, application: Application, today: date | None = None
) -> list[ExternalCheck]:
    """Опрашивает все источники параллельно и сохраняет ответы в external_checks.
    Отказ источника не прерывает сбор: проверка сохраняется со статусом failed.
    Коммит - на вызывающем."""
    company = await session.get(Company, application.company_id)
    assert company is not None
    sources = list(SOURCES)
    responses = await asyncio.gather(*(_call(s, company.inn, today) for s in sources))

    checks = []
    for source, (result, error) in zip(sources, responses, strict=True):
        check = ExternalCheck(
            application_id=application.id,
            source=source,
            status=CheckStatus.FAILED if error else CheckStatus.SUCCESS,
            result=result,
            error=error,
            completed_at=datetime.now(UTC),
        )
        session.add(check)
        checks.append(check)
    await session.flush()
    return checks


async def latest_results(
    session: AsyncSession, application_id: Any
) -> dict[CheckSource, dict[str, Any]]:
    """Последний успешный ответ каждого источника."""
    checks = await session.scalars(
        select(ExternalCheck)
        .where(
            ExternalCheck.application_id == application_id,
            ExternalCheck.status == CheckStatus.SUCCESS,
        )
        .order_by(ExternalCheck.created_at)
    )
    return {check.source: check.result for check in checks if check.result is not None}


async def application_features(
    session: AsyncSession, application: Application, today: date | None = None
) -> Features:
    return build_features(
        await latest_results(session, application.id),
        declared_revenue=application.annual_revenue,
        declared_monthly_debt_payments=application.monthly_debt_payments,
        today=today,
    )
