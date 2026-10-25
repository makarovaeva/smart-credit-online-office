import uuid

from fastapi import APIRouter, status

from app.api.deps import AUTH_RESPONSES, NOT_FOUND, CurrentUser, Limit, Offset, SessionDep
from app.schemas.notification import NotificationPage, NotificationRead
from app.services import notifications

router = APIRouter(prefix="/notifications", tags=["notifications"], responses=AUTH_RESPONSES)


@router.get("")
async def list_notifications(
    user: CurrentUser,
    session: SessionDep,
    unread_only: bool = False,
    limit: Limit = 20,
    offset: Offset = 0,
) -> NotificationPage:
    """Уведомления в кабинете, новые первыми. Клиенту - о событиях заявки (дозапрос, оффер,
    отказ, договор, зачисление), сотруднику - о назначении заявки, запросах и напоминаниях.
    unread - число непрочитанных для счётчика."""
    items, total, unread = await notifications.list_for(
        session, user, unread_only=unread_only, limit=limit, offset=offset
    )
    return NotificationPage(
        items=[NotificationRead.model_validate(n) for n in items],
        total=total,
        limit=limit,
        offset=offset,
        unread=unread,
    )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(user: CurrentUser, session: SessionDep) -> None:
    await notifications.mark_all_read(session, user)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def mark_read(notification_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    await notifications.mark_read(session, user, notification_id)
