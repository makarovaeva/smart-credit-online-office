import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ChatMessageType, ChatSender
from app.schemas.common import ORMModel


class ChatMessageRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    application_id: uuid.UUID | None
    sender_type: ChatSender
    message_type: ChatMessageType
    content: str
    card_payload: dict[str, Any] | None = Field(
        description="confirmation_card: {card_type: application_summary, fields: {amount, "
        "term_months, purpose, collateral_type, product_id, ...}, action: {action_type, status}}"
    )
    attachment_document_ids: list[uuid.UUID]
    info_request_ids: list[uuid.UUID]
    reply_to_id: uuid.UUID | None
    generated_by: str | None = Field(description="rules или llm:<модель>")
    created_at: datetime


class ChatMessageCreate(BaseModel):
    company_id: uuid.UUID
    # Без заявки - диалог до её создания (подбор параметров)
    application_id: uuid.UUID | None = None
    content: str = Field(min_length=1, max_length=2000)
    attachment_document_ids: list[uuid.UUID] = Field(default=[], max_length=20)
    # Ключ идемпотентности: повтор с тем же ключом возвращает уже сохранённую пару
    client_message_id: str | None = Field(default=None, min_length=1, max_length=64)


class ChatExchange(BaseModel):
    message: ChatMessageRead
    reply: ChatMessageRead
