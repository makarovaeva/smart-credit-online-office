import uuid

from fastapi import APIRouter, status

from app.api.deps import AUTH_RESPONSES, NOT_FOUND, CurrentUser, Limit, Offset, not_implemented
from app.schemas.common import Page
from app.schemas.notification import NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"], responses=AUTH_RESPONSES)


@router.get("")
async def list_notifications(
    user: CurrentUser, unread_only: bool = False, limit: Limit = 20, offset: Offset = 0
) -> Page[NotificationRead]:
    not_implemented()


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def mark_read(notification_id: uuid.UUID, user: CurrentUser) -> None:
    not_implemented()
