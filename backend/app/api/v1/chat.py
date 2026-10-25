import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AUTH_RESPONSES, NOT_FOUND, CurrentClient, SessionDep
from app.schemas.chat import ChatExchange, ChatMessageCreate, ChatMessageRead
from app.services import chat

router = APIRouter(prefix="/chat", tags=["chat"], responses=AUTH_RESPONSES | NOT_FOUND)


@router.get("/messages")
async def list_messages(
    user: CurrentClient,
    session: SessionDep,
    company_id: uuid.UUID,
    application_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ChatMessageRead]:
    """История диалога с ИИ-агентом, старые сообщения первыми. С application_id - только по
    заявке. Агент сам пишет в чат о событиях заявки: дозапрос документов, оффер, отказ
    с причиной, договор на подпись, зачисление средств."""
    messages = await chat.list_messages(session, user, company_id, application_id, limit)
    return [ChatMessageRead.model_validate(m) for m in messages]


@router.post("/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    body: ChatMessageCreate, user: CurrentClient, session: SessionDep
) -> ChatExchange:
    """Сообщение клиента и ответ агента. Из текста разбираются сумма, срок, цель и залог -
    ответ confirmation_card с параметрами и подходящим продуктом; заявку клиент создаёт
    и подаёт обычными командами. Ещё агент отвечает о статусе, документах, оффере, причине
    отказа и продуктах. Решений агент не принимает. Текст ответа - шаблон по данным заявки
    или, при заданном LLM_BASE_URL, формулировка модели с открытыми весами (generated_by).
    Повтор с тем же client_message_id возвращает сохранённую пару без дубля."""
    message, reply = await chat.send_message(session, user, body)
    return ChatExchange(
        message=ChatMessageRead.model_validate(message),
        reply=ChatMessageRead.model_validate(reply),
    )
