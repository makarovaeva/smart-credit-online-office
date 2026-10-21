import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DocumentType, InfoRequestStatus
from app.models.mixins import CreatedAtMixin, UUIDPkMixin, str_enum


class InfoRequest(UUIDPkMixin, CreatedAtMixin, Base):
    """Дозапрос информации у клиента: от системы (проверка полноты) или андеррайтера."""

    __tablename__ = "info_requests"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    # NULL - дозапрос сформирован автоматически
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    requested_document_types: Mapped[list[DocumentType]] = mapped_column(
        ARRAY(str_enum(DocumentType, check=False)), default=list
    )
    status: Mapped[InfoRequestStatus] = mapped_column(
        str_enum(InfoRequestStatus), default=InfoRequestStatus.OPEN
    )
    response_message: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(UUIDPkMixin, CreatedAtMixin, Base):
    """Файл заявки. Содержимое лежит в объектном хранилище, в БД только метаданные."""

    __tablename__ = "documents"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    info_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("info_requests.id"))
    type: Mapped[DocumentType] = mapped_column(str_enum(DocumentType))
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
