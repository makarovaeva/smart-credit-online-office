import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPkMixin


class Notification(UUIDPkMixin, CreatedAtMixin, Base):
    """Уведомление внутри кабинета: по условиям кейса email/SMS в сценарии не используются."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
