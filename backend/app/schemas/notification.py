import uuid
from datetime import datetime

from app.schemas.common import ORMModel, Page


class NotificationRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID | None
    type: str
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime


class NotificationPage(Page[NotificationRead]):
    unread: int
