import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ActorType, DocumentStatus, DocumentType, InfoRequestStatus
from app.schemas.common import ORMModel


class DocumentRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    info_request_id: uuid.UUID | None
    type: DocumentType
    file_name: str
    content_type: str
    size_bytes: int
    verification_status: DocumentStatus
    created_at: datetime


class InfoRequestRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    # system - ИИ (комплект документов), credit_analyst, underwriter
    requested_by: ActorType
    message: str
    requested_document_types: list[DocumentType]
    status: InfoRequestStatus
    response_message: str | None
    created_at: datetime
    answered_at: datetime | None


class InfoRequestCreate(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    requested_document_types: list[DocumentType] = []


class InfoRequestAnswer(BaseModel):
    """Документы к ответу загружаются заранее (с info_request_id или без него). Если в дозапросе
    перечислены типы документов, нужен хотя бы один файл каждого типа, иначе - сообщение."""

    message: str | None = Field(default=None, max_length=2000)
