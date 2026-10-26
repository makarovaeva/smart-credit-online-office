"""Кто работает с заявкой: на этапе аналитика - кредитный аналитик, андеррайтера - андеррайтер.

Сначала назначается тот, кто уже работал с этой заявкой (аналитик, писавший заключение;
андеррайтер, запросивший экспертизу или документы), иначе - наименее загруженный сотрудник роли.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, CreditDecision, CreditMemo, User
from app.models.enums import ApplicationStatus, NotificationType, UserRole
from app.services import notifications

STAGE_ROLES = {
    ApplicationStatus.ANALYST_ESCALATION: UserRole.CREDIT_ANALYST,
    ApplicationStatus.UNDERWRITER_REVIEW: UserRole.UNDERWRITER,
    # Подготовка договора кредитным аналитиком (CONTRACT_PREPARATION=analyst)
    ApplicationStatus.CONTRACT_GENERATION: UserRole.CREDIT_ANALYST,
}


async def _previous_performer(
    session: AsyncSession, application_id: uuid.UUID, role: UserRole
) -> uuid.UUID | None:
    if role == UserRole.CREDIT_ANALYST:
        query = select(CreditMemo.analyst_id).where(
            CreditMemo.application_id == application_id, CreditMemo.analyst_id.is_not(None)
        )
        order = CreditMemo.created_at
    else:
        query = select(CreditDecision.decided_by_id).where(
            CreditDecision.application_id == application_id
        )
        order = CreditDecision.created_at
    return await session.scalar(query.order_by(order.desc()).limit(1))


async def _least_loaded(session: AsyncSession, role: UserRole) -> uuid.UUID | None:
    load = (
        select(func.count(Application.id))
        .where(
            Application.assignee_id == User.id,
            Application.status.in_(list(STAGE_ROLES)),
        )
        .scalar_subquery()
    )
    return await session.scalar(
        select(User.id)
        .where(User.role == role, User.is_active)
        .order_by(load, User.created_at, User.id)
        .limit(1)
    )


async def _pick(session: AsyncSession, application: Application, role: UserRole):
    previous = await _previous_performer(session, application.id, role)
    if previous is not None:
        user = await session.get(User, previous)
        if user is not None and user.is_active and user.role == role:
            return previous
    return await _least_loaded(session, role)


STAGE_TITLES = {
    ApplicationStatus.ANALYST_ESCALATION: "Заявка на анализ",
    ApplicationStatus.UNDERWRITER_REVIEW: "Заявка на рассмотрение",
    ApplicationStatus.CONTRACT_GENERATION: "Подготовка договора",
}


async def auto_assign(
    session: AsyncSession, application: Application, preferred: uuid.UUID | None = None
) -> None:
    """Назначает исполнителя под текущий статус и уведомляет его; вне этапов сотрудников -
    снимает. preferred - выбранный сотрудник (например, аналитик для запроса экспертизы)."""
    role = STAGE_ROLES.get(application.status)
    if role is None:
        application.assignee_id = None
        return
    chosen = await session.get(User, preferred) if preferred else None
    if chosen is not None and chosen.is_active and chosen.role == role:
        application.assignee_id = chosen.id
    else:
        application.assignee_id = await _pick(session, application, role)
    if application.assignee_id is not None:
        notifications.add(
            session,
            [application.assignee_id],
            application,
            NotificationType.APPLICATION_ASSIGNED,
            f"{STAGE_TITLES[application.status]}: {application.number}",
            "Заявка назначена на вас и ждёт в очереди.",
        )
