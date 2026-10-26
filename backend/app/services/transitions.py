"""Единственное место, где меняется Application.status."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, ApplicationStatusHistory
from app.models.enums import ActorType, ApplicationStatus, CloseReason
from app.services import chat_events
from app.services.assignment import auto_assign
from app.services.status_machine import ensure_transition

S = ApplicationStatus

# Отметка времени, которую ставит вход в статус
_TIMESTAMPS = {
    S.SUBMITTED: "submitted_at",
    S.DISBURSEMENT: "signed_at",
    S.COMPLETED: "disbursed_at",
    S.CLOSED: "closed_at",
}


async def transition(
    session: AsyncSession,
    application: Application,
    target: ApplicationStatus,
    actor_type: ActorType,
    actor_id: uuid.UUID | None = None,
    *,
    comment: str | None = None,
    close_reason: CloseReason | None = None,
    assignee_id: uuid.UUID | None = None,
) -> None:
    """Проверяет переход по машине состояний, пишет его в историю, назначает исполнителя
    этапа и сообщает клиенту в чат о важных событиях. Коммит - на вызывающем."""
    ensure_transition(application.status, target, actor_type)
    if (target == S.CLOSED) != (close_reason is not None):
        raise ValueError("close_reason задаётся только и обязательно при закрытии заявки")

    session.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status=application.status,
            to_status=target,
            actor_type=actor_type,
            actor_id=actor_id,
            comment=comment,
        )
    )
    application.status = target
    if field := _TIMESTAMPS.get(target):
        setattr(application, field, datetime.now(UTC))
    if close_reason is not None:
        application.close_reason = close_reason
    await auto_assign(session, application, assignee_id)
    await chat_events.notify(session, application, comment)
    await session.flush()
