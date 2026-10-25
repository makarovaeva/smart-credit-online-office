"""Документы заявки и дозапросы.

Клиент загружает документы до подачи (draft, pre_approved) и по дозапросу
(need_additional_data). Дозапрос создают ИИ (проверка комплекта в конвейере), аналитик
(запрос документов через ИИ) и андеррайтер (решение more_information_required). Когда клиент
ответил на все открытые дозапросы, заявка возвращается к инициатору последнего из них.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePath

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Application, Document, InfoRequest, User
from app.models.enums import (
    ActorType,
    ApplicationStatus,
    DocumentStatus,
    DocumentType,
    InfoRequestStatus,
)
from app.schemas.document import InfoRequestAnswer, InfoRequestCreate
from app.services import pipeline, storage
from app.services.applications import get_client_application
from app.services.backoffice import get_visible_application
from app.services.decisions import ensure_assignee, get_application_for_update
from app.services.document_requirements import DOCUMENT_NAMES
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError
from app.services.status_machine import ensure_transition
from app.services.transitions import transition

S = ApplicationStatus

UPLOAD_STATUSES = frozenset({S.DRAFT, S.PRE_APPROVED, S.NEED_ADDITIONAL_DATA})

# Расширение -> (Content-Type, сигнатуры начала файла). Тип определяется по содержимому,
# Content-Type от клиента не используется
_FORMATS: dict[str, tuple[str, tuple[bytes, ...]]] = {
    ".pdf": ("application/pdf", (b"%PDF-",)),
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        (b"PK\x03\x04",),
    ),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        (b"PK\x03\x04",),
    ),
    ".xls": ("application/vnd.ms-excel", (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)),
    ".csv": ("text/csv", ()),
}
_READ_CHUNK = 1024 * 1024


# --- Документы ---


def _file_name(raw: str | None) -> str:
    """Только имя без каталогов и управляющих символов - для отображения и скачивания."""
    name = PurePath((raw or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    if not name or name in {".", ".."}:
        raise ValidationFailedError("У файла нет имени")
    return name[-255:]


def _content_type(name: str, head: bytes) -> str:
    extension = PurePath(name).suffix.lower()
    if extension not in _FORMATS:
        allowed = ", ".join(sorted(_FORMATS))
        raise ValidationFailedError(f"Формат файла не поддерживается. Допустимы: {allowed}")
    content_type, signatures = _FORMATS[extension]
    if signatures and not head.startswith(signatures):
        raise ValidationFailedError("Содержимое файла не соответствует расширению")
    if not signatures:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as exc:
            # Обрезанный на границе символа UTF-8 хвост допустим
            if exc.start < len(head) - 3:
                raise ValidationFailedError("CSV должен быть текстом в UTF-8") from exc
    return content_type


async def _read_limited(file: UploadFile) -> bytes:
    limit = get_settings().document_max_size_mb * 1024 * 1024
    chunks, size = [], 0
    while chunk := await file.read(_READ_CHUNK):
        size += len(chunk)
        if size > limit:
            raise ValidationFailedError(f"Файл больше {get_settings().document_max_size_mb} МБ")
        chunks.append(chunk)
    if size == 0:
        raise ValidationFailedError("Файл пустой")
    return b"".join(chunks)


async def _open_request(
    session: AsyncSession, application: Application, info_request_id: uuid.UUID
) -> InfoRequest:
    request = await session.get(InfoRequest, info_request_id, with_for_update=True)
    if request is None or request.application_id != application.id:
        raise NotFoundError("Дозапрос не найден")
    if request.status != InfoRequestStatus.OPEN:
        raise ConflictError("Дозапрос уже закрыт")
    return request


async def upload_document(
    session: AsyncSession,
    user: User,
    application_id: uuid.UUID,
    file: UploadFile,
    type: DocumentType,
    info_request_id: uuid.UUID | None,
) -> Document:
    application = await get_client_application(session, user, application_id, for_update=True)
    if application.status not in UPLOAD_STATUSES:
        raise ConflictError("Документы загружаются до подачи заявки или по дозапросу банка")
    if info_request_id is not None:
        await _open_request(session, application, info_request_id)
    name = _file_name(file.filename)
    content = await _read_limited(file)
    content_type = _content_type(name, content[:64])

    document_id = uuid.uuid4()
    key = f"applications/{application.id}/{document_id}{PurePath(name).suffix.lower()}"
    document = Document(
        id=document_id,
        application_id=application.id,
        info_request_id=info_request_id,
        type=type,
        file_name=name,
        content_type=content_type,
        size_bytes=len(content),
        storage_key=key,
        uploaded_by_id=user.id,
    )
    session.add(document)
    await session.flush()
    await asyncio.to_thread(storage.save, key, content)
    try:
        await session.commit()
    except Exception:
        await asyncio.to_thread(storage.delete, key)
        raise
    return document


async def _documents(session: AsyncSession, application_id: uuid.UUID) -> list[Document]:
    rows = await session.scalars(
        select(Document)
        .where(Document.application_id == application_id)
        .order_by(Document.created_at)
    )
    return list(rows)


async def list_documents(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> list[Document]:
    application = await get_client_application(session, user, application_id)
    return await _documents(session, application.id)


async def _document(
    session: AsyncSession, application: Application, document_id: uuid.UUID
) -> Document:
    document = await session.get(Document, document_id)
    if document is None or document.application_id != application.id:
        raise NotFoundError("Документ не найден")
    return document


def _content_path(document: Document) -> Path:
    path = storage.path_for(document.storage_key)
    if not path.is_file():
        raise NotFoundError("Файл документа не найден в хранилище")
    return path


async def get_client_document(
    session: AsyncSession, user: User, application_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, Path]:
    application = await get_client_application(session, user, application_id)
    document = await _document(session, application, document_id)
    return document, _content_path(document)


async def get_employee_document(
    session: AsyncSession, user: User, application_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, Path]:
    """Сотрудник скачивает файлы своих заявок (видимость - как у карточки)."""
    application = await get_visible_application(session, user, application_id)
    document = await _document(session, application, document_id)
    return document, _content_path(document)


async def delete_document(
    session: AsyncSession, user: User, application_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    """Удалить можно только ещё не проверенный ИИ документ на этапе загрузки."""
    application = await get_client_application(session, user, application_id, for_update=True)
    document = await _document(session, application, document_id)
    if application.status not in UPLOAD_STATUSES:
        raise ConflictError("Документы заявки на рассмотрении удалить нельзя")
    if document.verification_status != DocumentStatus.UPLOADED:
        raise ConflictError("Документ уже проверен банком")
    await session.delete(document)
    await session.commit()
    await asyncio.to_thread(storage.delete, document.storage_key)


# --- Дозапросы ---


async def _requests(session: AsyncSession, application_id: uuid.UUID) -> list[InfoRequest]:
    rows = await session.scalars(
        select(InfoRequest)
        .where(InfoRequest.application_id == application_id)
        .order_by(InfoRequest.created_at)
    )
    return list(rows)


async def list_info_requests(
    session: AsyncSession, user: User, application_id: uuid.UUID
) -> list[InfoRequest]:
    application = await get_client_application(session, user, application_id)
    return await _requests(session, application.id)


# Куда возвращается заявка после ответа - по инициатору дозапроса
RETURN_STATUS = {
    ActorType.SYSTEM: S.AI_VERIFICATION,
    ActorType.CREDIT_ANALYST: S.ANALYST_ESCALATION,
    ActorType.UNDERWRITER: S.UNDERWRITER_REVIEW,
}


async def answer_info_request(
    session: AsyncSession,
    user: User,
    application_id: uuid.UUID,
    info_request_id: uuid.UUID,
    body: InfoRequestAnswer,
) -> InfoRequest:
    application = await get_client_application(session, user, application_id, for_update=True)
    request = await _open_request(session, application, info_request_id)
    if application.status != S.NEED_ADDITIONAL_DATA:
        raise ConflictError("Заявка не ожидает ответа на дозапрос")

    # Документ закрывает дозапрос, если привязан к нему или загружен после его создания
    documents = [
        d
        for d in await _documents(session, application.id)
        if d.info_request_id == request.id
        or (d.info_request_id is None and d.created_at >= request.created_at)
    ]
    missing = [t for t in request.requested_document_types if t not in {d.type for d in documents}]
    if missing:
        names = ", ".join(DOCUMENT_NAMES[t] for t in missing)
        raise ValidationFailedError(f"Загрузите документы по запросу: {names}")
    if not request.requested_document_types and not (body.message and body.message.strip()):
        raise ValidationFailedError("Напишите ответ на запрос")

    now = datetime.now(UTC)
    for document in documents:
        if document.info_request_id is None and document.type in request.requested_document_types:
            document.info_request_id = request.id
    request.status = InfoRequestStatus.ANSWERED
    request.response_message = body.message
    request.answered_at = now
    await session.flush()

    requests = await _requests(session, application.id)
    if any(r.status == InfoRequestStatus.OPEN for r in requests):
        await session.commit()
        return request

    await transition(
        session,
        application,
        RETURN_STATUS[request.requested_by],
        ActorType.CLIENT,
        user.id,
        comment="Клиент ответил на дозапрос",
    )
    await session.commit()
    if application.status == S.AI_VERIFICATION:
        await pipeline.run_safely(session, application, pipeline.run_assessment)
    return request


async def request_documents_by_analyst(
    session: AsyncSession, analyst: User, application_id: uuid.UUID, body: InfoRequestCreate
) -> InfoRequest:
    """Аналитик запрашивает документы у клиента через ИИ-агента:
    analyst_escalation -> need_additional_data, после ответа - снова к аналитику."""
    application = await get_application_for_update(session, application_id)
    ensure_transition(application.status, S.NEED_ADDITIONAL_DATA, ActorType.CREDIT_ANALYST)
    ensure_assignee(application, analyst)
    request = InfoRequest(
        application_id=application.id,
        created_by_id=analyst.id,
        requested_by=ActorType.CREDIT_ANALYST,
        message=body.message,
        requested_document_types=body.requested_document_types,
    )
    session.add(request)
    await transition(
        session,
        application,
        S.NEED_ADDITIONAL_DATA,
        ActorType.CREDIT_ANALYST,
        analyst.id,
        comment=body.message,
    )
    await session.commit()
    return request
