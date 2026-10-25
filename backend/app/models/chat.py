import uuid
from typing import Any

from sqlalchemy import ARRAY, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ChatMessageType, ChatSender
from app.models.mixins import CreatedAtMixin, UUIDPkMixin, str_enum


class ChatMessage(UUIDPkMixin, CreatedAtMixin, Base):
    """Диалог клиента с ИИ-агентом (Chat History из документа модели данных).

    Диалог принадлежит компании-заёмщику; сообщение может относиться к заявке или быть до неё.
    Сообщения не редактируются и не удаляются.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("company_id", "client_message_id"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    # Автор-клиент; у сообщений агента - NULL
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    sender_type: Mapped[ChatSender] = mapped_column(str_enum(ChatSender))
    message_type: Mapped[ChatMessageType] = mapped_column(str_enum(ChatMessageType))
    content: Mapped[str] = mapped_column(Text)
    # Карточка подтверждения: {"card_type", "fields", "action"}
    card_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attachment_document_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    # Дозапросы, о которых говорит сообщение (requirement_ids в документе модели)
    info_request_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    # Ключ идемпотентности от клиента: повтор запроса не дублирует сообщение
    client_message_id: Mapped[str | None] = mapped_column(String(64))
    # Ответ на сообщение клиента (у сообщений агента)
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_messages.id"))
    # rules - шаблоны по данным заявки, llm:<модель> - текст сформулировала модель
    generated_by: Mapped[str | None] = mapped_column(String(100))
