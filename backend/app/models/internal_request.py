import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import InternalRequestStatus
from app.models.mixins import CreatedAtMixin, UUIDPkMixin, str_enum


class InternalRequest(UUIDPkMixin, CreatedAtMixin, Base):
    """Запрос экспертизы андеррайтера у кредитного аналитика (Internal Requests из документа
    модели данных): создаётся решением more_information_required с more_info_target=credit_analyst.
    Питает вкладку «Запросы от андеррайтера»."""

    __tablename__ = "internal_requests"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    from_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # Аналитик, принявший запрос
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[InternalRequestStatus] = mapped_column(
        str_enum(InternalRequestStatus), default=InternalRequestStatus.OPEN
    )
    message: Mapped[str] = mapped_column(Text)
    response_comment: Mapped[str | None] = mapped_column(Text)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
