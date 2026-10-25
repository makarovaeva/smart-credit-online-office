"""Запросы между сотрудниками и напоминания.

- Запрос экспертизы андеррайтера у аналитика (`internal_requests`): создаётся решением
  more_information_required с more_info_target=credit_analyst. Аналитик принимает его в работу,
  закрывает заключением или возвращает андеррайтеру с комментарием; андеррайтер может отозвать
  запрос и напомнить о нём.
- Дозапросы клиенту (`info_requests`) от аналитика или андеррайтера: инициатор может отозвать
  дозапрос и напомнить клиенту через ИИ-агента (сообщение в чате и уведомление).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, ChatMessage, InfoRequest, InternalRequest, User
from app.models.enums import (
    ActorType,
    ApplicationStatus,
    ChatMessageType,
    ChatSender,
    InfoRequestStatus,
    InternalRequestStatus,
    NotificationType,
    UserRole,
)
from app.services import notifications
from app.services.backoffice import get_visible_application
from app.services.decisions import ensure_assignee, get_application_for_update
from app.services.errors import ConflictError, ForbiddenError, NotFoundError
from app.services.transitions import transition

S = ApplicationStatus
ACTIVE = (InternalRequestStatus.OPEN, InternalRequestStatus.ACCEPTED)
ROLE_ACTOR = {
    UserRole.CREDIT_ANALYST: ActorType.CREDIT_ANALYST,
    UserRole.UNDERWRITER: ActorType.UNDERWRITER,
}


async def active_expertise_request(
    session: AsyncSession, application_id: uuid.UUID
) -> InternalRequest | None:
    return await session.scalar(
        select(InternalRequest)
        .where(
            InternalRequest.application_id == application_id,
            InternalRequest.status.in_(ACTIVE),
        )
        .order_by(InternalRequest.created_at.desc())
        .limit(1)
    )


async def _request(
    session: AsyncSession, application: Application, request_id: uuid.UUID
) -> InternalRequest:
    request = await session.get(InternalRequest, request_id, with_for_update=True)
    if request is None or request.application_id != application.id:
        raise NotFoundError("Запрос не найден")
    if request.status not in ACTIVE:
        raise ConflictError("Запрос уже закрыт")
    return request


async def accept(
    session: AsyncSession, analyst: User, application_id: uuid.UUID, request_id: uuid.UUID
) -> InternalRequest:
    """Аналитик принимает запрос экспертизы в работу. Повторное принятие - без изменений."""
    application = await get_application_for_update(session, application_id)
    # Закрытый запрос - 409 раньше проверки исполнителя: заявка уже могла уйти андеррайтеру
    request = await _request(session, application, request_id)
    ensure_assignee(application, analyst)
    if request.status == InternalRequestStatus.OPEN:
        request.status = InternalRequestStatus.ACCEPTED
        request.accepted_by_id = analyst.id
        request.accepted_at = datetime.now(UTC)
        await session.commit()
    return request


async def _back_to_underwriter(
    session: AsyncSession,
    application: Application,
    request: InternalRequest,
    status: InternalRequestStatus,
    actor: User,
    comment: str,
) -> None:
    if application.status != S.ANALYST_ESCALATION:
        raise ConflictError("Заявка не на этапе аналитика")
    request.status = status
    request.response_comment = comment
    request.closed_at = datetime.now(UTC)
    await transition(
        session,
        application,
        S.UNDERWRITER_REVIEW,
        ROLE_ACTOR[actor.role],
        actor.id,
        comment=comment,
    )


async def return_request(
    session: AsyncSession,
    analyst: User,
    application_id: uuid.UUID,
    request_id: uuid.UUID,
    comment: str,
) -> InternalRequest:
    """Аналитик возвращает запрос андеррайтеру с комментарием, без заключения:
    analyst_escalation -> underwriter_review."""
    application = await get_application_for_update(session, application_id)
    # Закрытый запрос - 409 раньше проверки исполнителя: заявка уже могла уйти андеррайтеру
    request = await _request(session, application, request_id)
    ensure_assignee(application, analyst)
    await _back_to_underwriter(
        session, application, request, InternalRequestStatus.RETURNED, analyst, comment
    )
    notifications.add(
        session,
        [request.from_user_id],
        application,
        NotificationType.REQUEST_RETURNED,
        f"Аналитик вернул запрос: {application.number}",
        comment,
    )
    await session.commit()
    return request


async def cancel_request(
    session: AsyncSession, underwriter: User, application_id: uuid.UUID, request_id: uuid.UUID
) -> InternalRequest:
    """Андеррайтер отзывает свой запрос экспертизы: заявка возвращается к нему."""
    application = await get_visible_application(
        session, underwriter, application_id, for_update=True
    )
    request = await _request(session, application, request_id)
    if request.from_user_id != underwriter.id:
        raise ForbiddenError("Отозвать запрос может его автор")
    analyst_id = application.assignee_id
    await _back_to_underwriter(
        session,
        application,
        request,
        InternalRequestStatus.CANCELLED,
        underwriter,
        "Андеррайтер отозвал запрос экспертизы",
    )
    if analyst_id:
        notifications.add(
            session,
            [analyst_id],
            application,
            NotificationType.STATUS_CHANGED,
            f"Запрос экспертизы отозван: {application.number}",
            "Андеррайтер отозвал запрос, заявка вернулась к нему.",
        )
    await session.commit()
    return request


async def remind_analyst(
    session: AsyncSession, underwriter: User, application_id: uuid.UUID, request_id: uuid.UUID
) -> InternalRequest:
    application = await get_visible_application(
        session, underwriter, application_id, for_update=True
    )
    request = await _request(session, application, request_id)
    if request.from_user_id != underwriter.id:
        raise ForbiddenError("Напомнить может автор запроса")
    if application.assignee_id is None:
        raise ConflictError("Заявка пока не назначена аналитику")
    notifications.add(
        session,
        [application.assignee_id],
        application,
        NotificationType.REMINDER,
        f"Напоминание по запросу экспертизы: {application.number}",
        request.message,
    )
    await session.commit()
    return request


# --- Дозапросы клиенту ---

# Кто из сотрудников управляет дозапросом: его инициатор
_INFO_OWNER = {
    ActorType.CREDIT_ANALYST: UserRole.CREDIT_ANALYST,
    ActorType.UNDERWRITER: UserRole.UNDERWRITER,
}
RETURN_STATUS = {
    UserRole.CREDIT_ANALYST: S.ANALYST_ESCALATION,
    UserRole.UNDERWRITER: S.UNDERWRITER_REVIEW,
}


async def _info_request(
    session: AsyncSession, application: Application, request_id: uuid.UUID, employee: User
) -> InfoRequest:
    request = await session.get(InfoRequest, request_id, with_for_update=True)
    if request is None or request.application_id != application.id:
        raise NotFoundError("Дозапрос не найден")
    if request.status != InfoRequestStatus.OPEN:
        raise ConflictError("Дозапрос уже закрыт")
    if _INFO_OWNER.get(request.requested_by) != employee.role:
        raise ForbiddenError("Управлять дозапросом может сотрудник, который его создал")
    return request


async def cancel_info_request(
    session: AsyncSession, employee: User, application_id: uuid.UUID, request_id: uuid.UUID
) -> InfoRequest:
    """Сотрудник отзывает свой дозапрос клиенту. Если открытых дозапросов не осталось, заявка
    возвращается к нему: need_additional_data -> analyst_escalation | underwriter_review."""
    application = await get_visible_application(session, employee, application_id, for_update=True)
    request = await _info_request(session, application, request_id, employee)
    request.status = InfoRequestStatus.CANCELLED
    await session.flush()
    still_open = await session.scalar(
        select(InfoRequest.id)
        .where(
            InfoRequest.application_id == application.id,
            InfoRequest.status == InfoRequestStatus.OPEN,
        )
        .limit(1)
    )
    if still_open is None and application.status == S.NEED_ADDITIONAL_DATA:
        await transition(
            session,
            application,
            RETURN_STATUS[employee.role],
            ROLE_ACTOR[employee.role],
            employee.id,
            comment="Дозапрос отозван",
        )
    await session.commit()
    return request


async def remind_client(
    session: AsyncSession, employee: User, application_id: uuid.UUID, request_id: uuid.UUID
) -> InfoRequest:
    """Напоминание клиенту через ИИ-агента: сообщение в чате и уведомление в кабинете."""
    application = await get_visible_application(session, employee, application_id, for_update=True)
    request = await _info_request(session, application, request_id, employee)
    text = f"Напоминаю: банк ждёт ответа на запрос. {request.message}"
    session.add(
        ChatMessage(
            company_id=application.company_id,
            application_id=application.id,
            sender_type=ChatSender.AI_AGENT,
            message_type=ChatMessageType.DOCUMENT_REQUEST,
            content=text,
            info_request_ids=[request.id],
            generated_by="rules",
        )
    )
    await notifications.to_company(
        session,
        application,
        NotificationType.REMINDER,
        f"Напоминание по заявке {application.number}",
        text,
    )
    await session.commit()
    return request
