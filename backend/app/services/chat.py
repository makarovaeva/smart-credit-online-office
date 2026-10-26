"""Чат клиента с ИИ-кредитным агентом.

Агент отвечает по фактам из backend: параметры кредита из текста клиента (карточка
подтверждения), статус заявки, дозапросы, оффер, причина отказа, продукты. Бизнес-команды
агент не выполняет: создание, подача, принятие оффера остаются отдельными командами API,
которые клиент подтверждает в интерфейсе.

Текст ответа строится по шаблону. Если задан LLM_BASE_URL, его формулирует модель с открытыми
весами по тем же фактам (services/llm.py); при ошибке модели остаётся шаблон.
"""

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ChatMessage,
    Company,
    CompanyMember,
    CreditDecision,
    CreditProduct,
    Document,
    InfoRequest,
    User,
)
from app.models.enums import (
    ApplicationStatus,
    ChatMessageType,
    ChatSender,
    CloseReason,
    CollateralType,
    DecisionType,
    InfoRequestStatus,
    LoanPurpose,
)
from app.schemas.chat import ChatMessageCreate
from app.services import llm
from app.services.applications import decline_reasons, to_read
from app.services.chat_events import pct, rub
from app.services.errors import NotFoundError, ValidationFailedError

S = ApplicationStatus
HISTORY_FOR_LLM = 10

PURPOSE_LABELS = {
    LoanPurpose.WORKING_CAPITAL: "Пополнение оборотных средств",
    LoanPurpose.EQUIPMENT: "Покупка оборудования",
    LoanPurpose.BUSINESS_EXPANSION: "Развитие бизнеса",
    LoanPurpose.REFINANCING: "Рефинансирование",
    LoanPurpose.OTHER: "Другая цель",
}
COLLATERAL_LABELS = {
    CollateralType.COMMERCIAL_REAL_ESTATE: "Коммерческая недвижимость",
    CollateralType.RESIDENTIAL_REAL_ESTATE: "Жилая недвижимость",
    CollateralType.VEHICLE: "Транспорт",
    CollateralType.EQUIPMENT: "Оборудование",
    CollateralType.INVENTORY: "Товары в обороте",
}

# --- Разбор параметров кредита из текста ---

_NUMBER = r"(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)"
_TERM_MONTHS = re.compile(_NUMBER + r"\s*(?:мес|месяц)", re.I)
_TERM_YEARS = re.compile(_NUMBER + r"\s*(?:год|года|лет)\b", re.I)
_AMOUNT = re.compile(
    _NUMBER + r"\s*(млн|миллион\w*|мл?н?\.|тыс\w*|т\.\s?р|к\b)?\s*(?:руб\w*|₽|р\.)?", re.I
)
_PURPOSES = (
    (("оборудован", "станок", "станк", "техник"), LoanPurpose.EQUIPMENT),
    (("рефинанс", "перекредит"), LoanPurpose.REFINANCING),
    (("оборот", "закуп", "товар", "сезон", "поставщик"), LoanPurpose.WORKING_CAPITAL),
    (("развит", "расширен", "открыт", "новую точку", "ремонт"), LoanPurpose.BUSINESS_EXPANSION),
)
_COLLATERALS = (
    (("коммерческ", "офис", "склад", "помещени"), CollateralType.COMMERCIAL_REAL_ESTATE),
    (("квартир", "дом", "жил"), CollateralType.RESIDENTIAL_REAL_ESTATE),
    (("авто", "машин", "транспорт", "грузовик"), CollateralType.VEHICLE),
    (("оборудован",), CollateralType.EQUIPMENT),
    (("товар",), CollateralType.INVENTORY),
)


def _to_decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(" ", "").replace(" ", "").replace(",", "."))


@dataclass
class LoanRequest:
    amount: Decimal | None = None
    term_months: int | None = None
    purpose: LoanPurpose | None = None
    has_collateral: bool | None = None
    collateral_type: CollateralType | None = None

    def found(self) -> bool:
        return self.amount is not None or self.term_months is not None


def parse_loan_request(text: str) -> LoanRequest:
    """«3 млн на 2 года на оборотку без залога» -> сумма, срок, цель, залог."""
    lower = text.lower()
    request = LoanRequest()
    rest = lower
    if match := _TERM_MONTHS.search(rest):
        request.term_months = int(_to_decimal(match.group(1)))
        rest = rest[: match.start()] + rest[match.end() :]
    elif match := _TERM_YEARS.search(rest):
        request.term_months = int(_to_decimal(match.group(1)) * 12)
        rest = rest[: match.start()] + rest[match.end() :]
    elif "полгода" in rest:
        request.term_months = 6
    elif re.search(r"\bна год\b", rest):
        request.term_months = 12

    for match in _AMOUNT.finditer(rest):
        value, unit = _to_decimal(match.group(1)), (match.group(2) or "").lower()
        if unit.startswith(("млн", "миллион", "мл")):
            value *= 1_000_000
        elif unit.startswith(("тыс", "т.", "к")):
            value *= 1_000
        elif value < 10_000:
            continue  # голое небольшое число - не сумма кредита
        request.amount = value.quantize(Decimal("0.01"))
        break

    # Цель - в тексте до упоминания залога: «под залог оборудования» - не цель кредита
    head = lower.split("залог")[0]
    request.purpose = next(
        (purpose for words, purpose in _PURPOSES if any(w in head for w in words)), None
    )
    if "без залог" in lower or "без обеспечен" in lower:
        request.has_collateral = False
    elif "залог" in lower or "обеспечени" in lower:
        request.has_collateral = True
        tail = lower[lower.find("залог") :] if "залог" in lower else lower
        request.collateral_type = next(
            (kind for words, kind in _COLLATERALS if any(w in tail for w in words)), None
        )
    return request


# --- Контекст: факты, на которые опирается ответ ---


@dataclass
class Context:
    company: Company
    application: Application | None
    products: list[CreditProduct]
    application_facts: dict[str, Any] | None = None
    open_requests: list[InfoRequest] = field(default_factory=list)
    decision: CreditDecision | None = None
    decline_reason: str | None = None
    # Что можно изменить, чтобы следующая заявка прошла (советы по стоп-факторам)
    decline_advice: list[str] = field(default_factory=list)


async def _context(
    session: AsyncSession, company: Company, application: Application | None
) -> Context:
    products = list(
        await session.scalars(
            select(CreditProduct)
            .where(CreditProduct.is_active.is_(True))
            .order_by(CreditProduct.min_amount)
        )
    )
    context = Context(company=company, application=application, products=products)
    if application is None:
        return context
    read = await to_read(session, application)
    context.application_facts = {
        "number": read.number,
        "status": read.client_status,
        "status_description": read.status_description,
        "requested_amount": application.requested_amount,
        "requested_term_months": application.requested_term_months,
        "available_actions": [str(a) for a in read.available_actions],
    }
    context.open_requests = list(
        await session.scalars(
            select(InfoRequest)
            .where(
                InfoRequest.application_id == application.id,
                InfoRequest.status == InfoRequestStatus.OPEN,
            )
            .order_by(InfoRequest.created_at)
        )
    )
    context.decision = await session.scalar(
        select(CreditDecision)
        .where(CreditDecision.application_id == application.id)
        .order_by(CreditDecision.created_at.desc())
        .limit(1)
    )
    if application.close_reason in (CloseReason.AUTO_DECLINED, CloseReason.UNDERWRITER_DECLINED):
        # Причины и советы - те же, что клиент видит в заявке (decline_reasons)
        reasons = await decline_reasons(session, application)
        context.decline_reason = "; ".join(r.message for r in reasons) or None
        context.decline_advice = [r.advice for r in reasons if r.advice]
    return context


def _facts_text(context: Context) -> str:
    """Факты для LLM: только то, что знает backend."""
    lines = [f"Компания: {context.company.name}, ИНН {context.company.inn}."]
    if context.application_facts:
        f = context.application_facts
        lines.append(
            f"Заявка {f['number']}: {rub(f['requested_amount'])} на "
            f"{f['requested_term_months']} мес. Статус для клиента: {f['status']} - "
            f"{f['status_description']}. Доступные клиенту действия: "
            f"{', '.join(f['available_actions']) or 'нет'}."
        )
    else:
        lines.append("Заявки в этом диалоге пока нет.")
    lines += [f"Открытый запрос банка: {r.message}" for r in context.open_requests]
    decision = context.decision
    if decision and decision.decision_type in (
        DecisionType.APPROVED,
        DecisionType.CONDITIONAL_APPROVAL,
    ):
        lines.append(
            f"Решение банка: {decision.decision_type}, {rub(decision.approved_amount)} на "
            f"{decision.approved_term_months} мес. под {pct(decision.interest_rate)}."
        )
    if context.decline_reason:
        lines.append(f"Причина отказа: {context.decline_reason}")
    lines.append(
        "Продукты: "
        + "; ".join(
            f"{p.name} от {rub(p.min_amount)} до {rub(p.max_amount)}, "
            f"{p.min_term_months}-{p.max_term_months} мес., ставка от {pct(p.base_rate)}"
            for p in context.products
        )
    )
    return "\n".join(lines)


# --- Ответ агента по шаблонам ---


@dataclass
class Reply:
    message_type: ChatMessageType
    content: str
    card_payload: dict[str, Any] | None = None
    info_request_ids: list[uuid.UUID] = field(default_factory=list)


def _match_product(request: LoanRequest, products: list[CreditProduct]) -> CreditProduct | None:
    purpose = request.purpose or LoanPurpose.WORKING_CAPITAL
    for product in products:
        if purpose not in product.purposes:
            continue
        if request.amount is not None and not (
            product.min_amount <= request.amount <= product.max_amount
        ):
            continue
        if request.term_months is not None and not (
            product.min_term_months <= request.term_months <= product.max_term_months
        ):
            continue
        if product.requires_collateral and request.has_collateral is False:
            continue
        return product
    return None


def _card(request: LoanRequest, context: Context) -> Reply:
    application = context.application
    editable = application is not None and application.status in (S.DRAFT, S.PRE_APPROVED)
    # Недостающее берётся из текущего черновика
    amount = request.amount or (application.requested_amount if editable else None)
    term = request.term_months or (application.requested_term_months if editable else None)
    purpose = request.purpose or (application.purpose if editable else None)
    merged = LoanRequest(amount, term, purpose, request.has_collateral, request.collateral_type)
    product = _match_product(merged, context.products)
    fields = {
        "amount": f"{amount:.2f}" if amount is not None else None,
        "term_months": term,
        "purpose": purpose,
        "purpose_label": PURPOSE_LABELS.get(purpose) if purpose else None,
        "has_collateral": merged.has_collateral,
        "collateral_type": merged.collateral_type,
        "collateral_label": (
            COLLATERAL_LABELS.get(merged.collateral_type)
            if merged.collateral_type
            else "Без залога"
            if merged.has_collateral is False
            else "Залог, тип не указан"
            if merged.has_collateral
            else None
        ),
        "product_id": str(product.id) if product else None,
        "product_name": product.name if product else None,
    }
    missing = [
        name
        for name, value in (("сумму", amount), ("срок", term), ("цель", purpose))
        if value is None
    ]
    parts = []
    if amount is not None:
        parts.append(rub(amount))
    if term is not None:
        parts.append(f"на {term} мес.")
    if purpose is not None:
        parts.append(PURPOSE_LABELS[purpose].lower())
    text = "Правильно понимаю: " + " ".join(parts) + "?"
    if missing:
        text += " Уточните, пожалуйста, " + " и ".join(missing) + "."
    elif product is None:
        text += " Подходящего продукта на этих условиях нет - попробуйте изменить сумму или срок."
    else:
        text += (
            f" Подойдёт продукт «{product.name}» со ставкой от {pct(product.base_rate)} годовых."
        )
        text += " Проверьте параметры и подтвердите заявку."
    action = "update_application" if editable else "create_application"
    return Reply(
        ChatMessageType.CONFIRMATION_CARD,
        text,
        card_payload={
            "card_type": "application_summary",
            "fields": fields,
            "action": {"action_type": action, "status": "pending" if not missing else "incomplete"},
        },
    )


def _status(context: Context) -> Reply:
    facts = context.application_facts
    if facts is None:
        return Reply(
            ChatMessageType.TEXT,
            "Заявки пока нет. Напишите, сколько нужно, на какой срок и на что - например, "
            "«3 млн на 2 года на пополнение оборотных средств».",
        )
    text = f"Заявка {facts['number']}: {facts['status_description']}."
    if context.open_requests:
        text += " Банк ждёт от вас документы - спросите «какие документы нужны»."
    return Reply(ChatMessageType.TEXT, text)


def _documents(context: Context) -> Reply:
    if not context.open_requests:
        text = "Сейчас банк не ждёт от вас документов."
        if context.application and context.application.status in (S.DRAFT, S.PRE_APPROVED):
            text += " Можно заранее загрузить выписку или отчётность - проверка пройдёт быстрее."
        return Reply(ChatMessageType.TEXT, text)
    return Reply(
        ChatMessageType.DOCUMENT_REQUEST,
        "\n".join(r.message for r in context.open_requests)
        + "\nЗагрузите файлы в разделе заявки и ответьте на запрос.",
        info_request_ids=[r.id for r in context.open_requests],
    )


def _offer(context: Context) -> Reply:
    decision = context.decision
    if decision is None or decision.decision_type not in (
        DecisionType.APPROVED,
        DecisionType.CONDITIONAL_APPROVAL,
    ):
        return Reply(
            ChatMessageType.TEXT,
            "Предложения банка пока нет: оно появится после рассмотрения заявки. "
            + (
                f"Ориентир по ставке - от {pct(min(p.base_rate for p in context.products))}"
                " годовых."
                if context.products
                else ""
            ),
        )
    kind = (
        " на изменённых условиях"
        if decision.decision_type == DecisionType.CONDITIONAL_APPROVAL
        else ""
    )
    text = (
        f"Предложение банка{kind}: {rub(decision.approved_amount)} на "
        f"{decision.approved_term_months} мес. под {pct(decision.interest_rate)} годовых."
    )
    if context.application and context.application.status == S.OFFER_GENERATED:
        text += " Примите или отклоните его в разделе заявки."
    return Reply(ChatMessageType.TEXT, text)


def _decline(context: Context) -> Reply:
    if context.decline_reason:
        return Reply(
            ChatMessageType.REJECTION_NOTICE,
            f"Причина отказа: {context.decline_reason}."
            + (
                " Что можно сделать: " + "; ".join(context.decline_advice) + "."
                if context.decline_advice
                else " Можно подать новую заявку, когда ситуация изменится."
            ),
        )
    return Reply(ChatMessageType.TEXT, "По этой заявке отказа нет.")


def _products(context: Context) -> Reply:
    lines = [
        f"• {p.name}: {rub(p.min_amount)} - {rub(p.max_amount)}, "
        f"{p.min_term_months}-{p.max_term_months} мес., ставка от {pct(p.base_rate)}"
        + (", нужен залог" if p.requires_collateral else "")
        for p in context.products
    ]
    return Reply(ChatMessageType.TEXT, "Кредиты для бизнеса:\n" + "\n".join(lines))


HELP = (
    "Я ИИ-агент банка. Помогу оформить кредит: напишите сумму, срок и цель - например, "
    "«5 млн на 3 года на закупку товара». Ещё могу рассказать о статусе заявки, нужных "
    "документах, предложении банка и причинах решения. Решение по кредиту принимает банк."
)

_INTENTS = (
    (("отказ", "почему", "причин", "исправ", "что можно сделать"), _decline),
    (("документ", "выписк", "дозапрос", "загруз", "файл", "отчётност", "отчетност"), _documents),
    (("оффер", "предложени", "ставк", "платеж", "платёж", "одобр"), _offer),
    (("статус", "заявк", "когда", "что с", "этап", "рассмотр", "решени"), _status),
    (("продукт", "какие кредит", "кредиты", "условия кредит"), _products),
)


def rule_reply(text: str, context: Context) -> Reply:
    lower = text.lower()
    request = parse_loan_request(text)
    if request.found() and not any(w in lower for w in ("платеж", "платёж", "оффер")):
        return _card(request, context)
    for words, handler in _INTENTS:
        if any(w in lower for w in words):
            # «Почему» без отказа - вопрос о статусе
            if handler is _decline and context.decline_reason is None:
                continue
            return handler(context)
    if any(w in lower for w in ("привет", "здравств", "добрый")):
        return Reply(ChatMessageType.TEXT, "Здравствуйте! " + HELP)
    return Reply(ChatMessageType.TEXT, HELP)


# --- Сообщения ---


async def _company_for(session: AsyncSession, user: User, company_id: uuid.UUID) -> Company:
    member = await session.scalar(
        select(CompanyMember.id).where(
            CompanyMember.company_id == company_id, CompanyMember.user_id == user.id
        )
    )
    company = await session.get(Company, company_id) if member else None
    if company is None:
        raise NotFoundError("Компания не найдена")
    return company


async def _application_for(
    session: AsyncSession, company: Company, application_id: uuid.UUID | None
) -> Application | None:
    if application_id is None:
        return None
    application = await session.get(Application, application_id)
    if application is None or application.company_id != company.id:
        raise NotFoundError("Заявка не найдена")
    return application


async def list_messages(
    session: AsyncSession,
    user: User,
    company_id: uuid.UUID,
    application_id: uuid.UUID | None,
    limit: int,
) -> list[ChatMessage]:
    """Последние сообщения диалога в хронологическом порядке. С application_id - только
    по этой заявке, без него - весь диалог компании."""
    company = await _company_for(session, user, company_id)
    query = select(ChatMessage).where(ChatMessage.company_id == company.id)
    if application_id is not None:
        await _application_for(session, company, application_id)
        query = query.where(ChatMessage.application_id == application_id)
    rows = await session.scalars(query.order_by(ChatMessage.created_at.desc()).limit(limit))
    return list(reversed(list(rows)))


async def _existing_exchange(
    session: AsyncSession, company: Company, client_message_id: str
) -> tuple[ChatMessage, ChatMessage] | None:
    message = await session.scalar(
        select(ChatMessage).where(
            ChatMessage.company_id == company.id,
            ChatMessage.client_message_id == client_message_id,
        )
    )
    if message is None:
        return None
    reply = await session.scalar(select(ChatMessage).where(ChatMessage.reply_to_id == message.id))
    assert reply is not None
    return message, reply


async def _history(session: AsyncSession, company: Company, application: Application | None):
    query = select(ChatMessage).where(ChatMessage.company_id == company.id)
    if application is not None:
        query = query.where(ChatMessage.application_id == application.id)
    rows = await session.scalars(
        query.order_by(ChatMessage.created_at.desc()).limit(HISTORY_FOR_LLM)
    )
    return [
        ("user" if m.sender_type == ChatSender.CLIENT else "assistant", m.content)
        for m in reversed(list(rows))
    ]


async def send_message(
    session: AsyncSession, user: User, body: ChatMessageCreate
) -> tuple[ChatMessage, ChatMessage]:
    company = await _company_for(session, user, body.company_id)
    if body.client_message_id is not None:
        existing = await _existing_exchange(session, company, body.client_message_id)
        if existing is not None:
            return existing
    application = await _application_for(session, company, body.application_id)
    if body.attachment_document_ids:
        if application is None:
            raise ValidationFailedError("Документы прикладываются к сообщению по заявке")
        owned = set(
            await session.scalars(
                select(Document.id).where(
                    Document.application_id == application.id,
                    Document.id.in_(body.attachment_document_ids),
                )
            )
        )
        if owned != set(body.attachment_document_ids):
            raise ValidationFailedError("Можно приложить только документы этой заявки")

    context = await _context(session, company, application)
    history = await _history(session, company, application)
    reply = rule_reply(body.content, context)
    generated_by = "rules"
    if text := await llm.rephrase(_facts_text(context), history, body.content, reply.content):
        reply.content, generated_by = text, f"llm:{llm.model_name()}"

    message = ChatMessage(
        company_id=company.id,
        application_id=application.id if application else None,
        user_id=user.id,
        sender_type=ChatSender.CLIENT,
        message_type=ChatMessageType.TEXT,
        content=body.content,
        attachment_document_ids=body.attachment_document_ids,
        client_message_id=body.client_message_id,
    )
    session.add(message)
    await session.flush()
    answer = ChatMessage(
        company_id=company.id,
        application_id=message.application_id,
        sender_type=ChatSender.AI_AGENT,
        message_type=reply.message_type,
        content=reply.content,
        card_payload=reply.card_payload,
        info_request_ids=reply.info_request_ids,
        reply_to_id=message.id,
        generated_by=generated_by,
    )
    session.add(answer)
    try:
        await session.commit()
    except IntegrityError:
        # Параллельный повтор с тем же client_message_id успел первым
        await session.rollback()
        existing = await _existing_exchange(session, company, body.client_message_id or "")
        if existing is None:
            raise
        return existing
    return message, answer
