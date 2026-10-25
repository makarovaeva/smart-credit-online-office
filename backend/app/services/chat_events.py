"""Сообщения ИИ-агента в чате о событиях заявки: весь сценарий - внутри продукта.

Вызывается из transitions.transition() для этапов, о которых клиенту нужно узнать.
Сообщение пишется в той же транзакции, что и смена статуса.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, ChatMessage, CreditDecision, InfoRequest
from app.models.enums import (
    ApplicationStatus,
    ChatMessageType,
    ChatSender,
    CloseReason,
    DecisionType,
    InfoRequestStatus,
    NotificationType,
)
from app.services import notifications

S = ApplicationStatus


def rub(value: Decimal | int | float | None) -> str:
    """3000000 -> «3 000 000 ₽», с копейками - два знака."""
    if value is None:
        return "—"
    amount = Decimal(value)
    text = f"{amount:,.0f}" if amount == amount.to_integral() else f"{amount:,.2f}"
    return text.replace(",", " ").replace(".", ",") + " ₽"


async def _latest_decision(session: AsyncSession, application_id) -> CreditDecision | None:
    return await session.scalar(
        select(CreditDecision)
        .where(CreditDecision.application_id == application_id)
        .order_by(CreditDecision.created_at.desc())
        .limit(1)
    )


async def _documents_message(session: AsyncSession, application: Application) -> ChatMessage:
    requests = list(
        await session.scalars(
            select(InfoRequest)
            .where(
                InfoRequest.application_id == application.id,
                InfoRequest.status == InfoRequestStatus.OPEN,
            )
            .order_by(InfoRequest.created_at)
        )
    )
    lines = [r.message for r in requests] or ["Банку нужны дополнительные данные по заявке."]
    return _message(
        application,
        ChatMessageType.DOCUMENT_REQUEST,
        "\n".join(lines) + "\nЗагрузите файлы в разделе заявки и ответьте на запрос.",
        info_request_ids=[r.id for r in requests],
    )


async def _offer_message(session: AsyncSession, application: Application) -> ChatMessage:
    decision = await _latest_decision(session, application.id)
    assert decision is not None
    terms = (
        f"{rub(decision.approved_amount)} на {decision.approved_term_months} мес. "
        f"под {decision.interest_rate}% годовых"
    )
    if decision.decision_type == DecisionType.CONDITIONAL_APPROVAL:
        text = f"Банк предлагает кредит на изменённых условиях: {terms}."
    else:
        text = f"Кредит одобрен: {terms}."
    if decision.valid_until:
        text += f" Предложение действует до {decision.valid_until:%d.%m.%Y}."
    return _message(application, ChatMessageType.STATUS_NOTIFICATION, text)


async def _closed_message(
    session: AsyncSession, application: Application, comment: str | None
) -> ChatMessage | None:
    match application.close_reason:
        case CloseReason.AUTO_DECLINED:
            reasons = (comment or "").removeprefix("Автоматический отказ: ")
            text = f"К сожалению, банк не может выдать кредит. Причина: {reasons}."
        case CloseReason.UNDERWRITER_DECLINED:
            decision = await _latest_decision(session, application.id)
            reasons = "; ".join(r["message"] for r in (decision.reasons if decision else []))
            text = "К сожалению, банк отказал в кредите"
            text += f". Причина: {reasons}." if reasons else "."
        case CloseReason.OFFER_REJECTED:
            text = "Вы отказались от предложения банка, заявка закрыта."
        case CloseReason.CLIENT_CANCELLED:
            return _message(
                application,
                ChatMessageType.STATUS_NOTIFICATION,
                "Заявка отменена по вашему запросу.",
            )
        case _:
            return None
    return _message(application, ChatMessageType.REJECTION_NOTICE, text)


def _message(
    application: Application, message_type: ChatMessageType, content: str, **extra
) -> ChatMessage:
    return ChatMessage(
        company_id=application.company_id,
        application_id=application.id,
        sender_type=ChatSender.AI_AGENT,
        message_type=message_type,
        content=content,
        generated_by="rules",
        **extra,
    )


# Уведомление в кабинете к сообщению агента: тип и заголовок по этапу
_NOTIFICATIONS = {
    S.NEED_ADDITIONAL_DATA: (NotificationType.DOCUMENT_REQUEST, "Банку нужны документы"),
    S.OFFER_GENERATED: (NotificationType.OFFER_READY, "Предложение банка готово"),
    S.E_SIGN: (NotificationType.CONTRACT_TO_SIGN, "Договор готов к подписанию"),
    S.COMPLETED: (NotificationType.FUNDS_DISBURSED, "Средства зачислены"),
}


async def notify(
    session: AsyncSession, application: Application, comment: str | None = None
) -> None:
    """Сообщение агента в чат и уведомление представителям компании о новом статусе заявки
    (статус уже сменён)."""
    message: ChatMessage | None
    match application.status:
        case S.NEED_ADDITIONAL_DATA:
            message = await _documents_message(session, application)
        case S.OFFER_GENERATED:
            message = await _offer_message(session, application)
        case S.CLOSED:
            message = await _closed_message(session, application, comment)
        case S.E_SIGN:
            message = _message(
                application,
                ChatMessageType.STATUS_NOTIFICATION,
                "Кредитный договор и график платежей готовы. Проверьте их и подпишите договор.",
            )
        case S.COMPLETED:
            message = _message(
                application,
                ChatMessageType.STATUS_NOTIFICATION,
                "Средства зачислены на расчётный счёт. Кредит появился в разделе «Кредиты».",
            )
        case _:
            message = None
    if message is None:
        return
    session.add(message)
    if application.status == S.CLOSED:
        declined = message.message_type == ChatMessageType.REJECTION_NOTICE
        kind, title = (
            (NotificationType.APPLICATION_DECLINED, "Решение по заявке")
            if declined
            else (NotificationType.STATUS_CHANGED, "Заявка закрыта")
        )
    else:
        kind, title = _NOTIFICATIONS[application.status]
    await notifications.to_company(
        session, application, kind, f"{title}: {application.number}", message.content
    )
