import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import (
    AUTH_RESPONSES,
    CONFLICT,
    NOT_FOUND,
    CurrentClient,
    Limit,
    Offset,
    SessionDep,
    file_response,
)
from app.models.enums import ApplicationStatus, DocumentType
from app.schemas.application import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationShort,
    ApplicationUpdate,
    ConsentRead,
    ConsentsRequest,
    PreApprovalRead,
    SignRequest,
    StatusHistoryItem,
)
from app.schemas.common import Page
from app.schemas.decision import OfferRead, RejectOfferRequest
from app.schemas.document import DocumentRead, InfoRequestAnswer, InfoRequestRead
from app.schemas.loan import LoanContractRead
from app.services import applications as service
from app.services import documents, loans, offers

router = APIRouter(
    prefix="/applications", tags=["applications"], responses=AUTH_RESPONSES | NOT_FOUND
)

ApplicationId = uuid.UUID


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_application(
    body: ApplicationCreate, user: CurrentClient, session: SessionDep
) -> ApplicationRead:
    """Создать черновик заявки."""
    application = await service.create_application(session, user, body)
    return await service.to_read(session, application)


@router.get("")
async def list_applications(
    user: CurrentClient,
    session: SessionDep,
    status_in: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    company_id: uuid.UUID | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[ApplicationShort]:
    """Заявки компаний пользователя, новые первыми."""
    items, total = await service.list_applications(
        session, user, statuses=status_in, company_id=company_id, limit=limit, offset=offset
    )
    return Page(
        items=[ApplicationShort.model_validate(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{application_id}")
async def get_application(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> ApplicationRead:
    """Заявка с понятным описанием этапа и списком доступных действий."""
    application = await service.get_client_application(session, user, application_id)
    return await service.to_read(session, application)


@router.patch("/{application_id}", responses=CONFLICT)
async def update_application(
    application_id: ApplicationId, body: ApplicationUpdate, user: CurrentClient, session: SessionDep
) -> ApplicationRead:
    """Изменить черновик или дополнить данные по дозапросу.
    Сумма, срок, цель и продукт меняются только до подачи (draft, pre_approved),
    финансовые показатели и залог - ещё и в need_additional_data."""
    application = await service.update_application(session, user, application_id, body)
    return await service.to_read(session, application)


# --- Согласия и предварительный лимит ---


@router.post("/{application_id}/consents", responses=CONFLICT)
async def give_consents(
    application_id: ApplicationId, body: ConsentsRequest, user: CurrentClient, session: SessionDep
) -> ApplicationRead:
    """Дать согласия на получение данных (БКИ, ФНС, цифровой профиль), нужны все три.
    draft -> data_collection: ИИ собирает данные и рассчитывает предварительный лимит."""
    application = await service.give_consents(session, user, application_id, body.types)
    return await service.to_read(session, application)


@router.get("/{application_id}/consents")
async def list_consents(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> list[ConsentRead]:
    consents = await service.list_consents(session, user, application_id)
    return [ConsentRead.model_validate(c) for c in consents]


@router.get("/{application_id}/pre-approval")
async def get_pre_approval(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> PreApprovalRead:
    """Вероятность одобрения, диапазон суммы, прогнозируемая ставка,
    необходимость обеспечения и рекомендации."""
    pre_approval = await service.get_pre_approval(session, user, application_id)
    return PreApprovalRead.model_validate(pre_approval)


@router.post("/{application_id}/pre-approval/decline", responses=CONFLICT)
async def decline_pre_approval(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> ApplicationRead:
    """Клиент не продолжает после предварительного расчёта: pre_approved -> closed
    (close_reason = pre_approval_declined)."""
    application = await service.decline_pre_approval(session, user, application_id)
    return await service.to_read(session, application)


@router.post("/{application_id}/submit", responses=CONFLICT)
async def submit_application(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> ApplicationRead:
    """Подтвердить сумму, срок, цель и согласие на проверки: pre_approved -> submitted.
    Запускает анализ ИИ."""
    application = await service.submit_application(session, user, application_id)
    return await service.to_read(session, application)


@router.get("/{application_id}/history")
async def get_history(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> list[StatusHistoryItem]:
    """Таймлайн заявки."""
    history = await service.get_history(session, user, application_id)
    return [StatusHistoryItem.model_validate(h) for h in history]


# --- Документы ---


@router.post("/{application_id}/documents", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def upload_document(
    application_id: ApplicationId,
    user: CurrentClient,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    type: Annotated[DocumentType, Form()],
    info_request_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentRead:
    """Загрузить документ: до подачи (draft, pre_approved) или по дозапросу
    (need_additional_data, можно указать info_request_id). Форматы: PDF, PNG, JPEG, XLSX, XLS,
    DOCX, CSV; содержимое должно соответствовать расширению; размер - до
    DOCUMENT_MAX_SIZE_MB (20 МБ)."""
    document = await documents.upload_document(
        session, user, application_id, file, type, info_request_id
    )
    return DocumentRead.model_validate(document)


@router.get("/{application_id}/documents")
async def list_documents(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> list[DocumentRead]:
    return [
        DocumentRead.model_validate(d)
        for d in await documents.list_documents(session, user, application_id)
    ]


@router.get(
    "/{application_id}/documents/{document_id}/content",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_document(
    application_id: ApplicationId,
    document_id: uuid.UUID,
    user: CurrentClient,
    session: SessionDep,
) -> FileResponse:
    document, path = await documents.get_client_document(session, user, application_id, document_id)
    return file_response(document, path)


@router.delete(
    "/{application_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_document(
    application_id: ApplicationId,
    document_id: uuid.UUID,
    user: CurrentClient,
    session: SessionDep,
) -> None:
    """Удалить документ, который банк ещё не проверил, - только на этапах загрузки."""
    await documents.delete_document(session, user, application_id, document_id)


# --- Дозапросы ---


@router.get("/{application_id}/info-requests")
async def list_info_requests(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> list[InfoRequestRead]:
    """Дозапросы банка: от ИИ (комплект документов), аналитика или андеррайтера."""
    return [
        InfoRequestRead.model_validate(r)
        for r in await documents.list_info_requests(session, user, application_id)
    ]


@router.post("/{application_id}/info-requests/{info_request_id}/answer", responses=CONFLICT)
async def answer_info_request(
    application_id: ApplicationId,
    info_request_id: uuid.UUID,
    body: InfoRequestAnswer,
    user: CurrentClient,
    session: SessionDep,
) -> InfoRequestRead:
    """Ответить на дозапрос: сначала загрузить запрошенные документы (по файлу каждого типа),
    без запрошенных документов нужен текст ответа. Когда закрыты все открытые дозапросы,
    заявка возвращается к инициатору: ИИ - need_additional_data -> ai_verification
    (повторная проверка комплекта, конвейер продолжается), аналитик -> analyst_escalation,
    андеррайтер -> underwriter_review."""
    request = await documents.answer_info_request(
        session, user, application_id, info_request_id, body
    )
    return InfoRequestRead.model_validate(request)


# --- Оффер и выдача ---


@router.get("/{application_id}/offer")
async def get_offer(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> OfferRead:
    """Оффер: сумма, ставка, срок, условия и причины решения.
    decision_type = conditional_approval - контр-предложение на изменённых условиях."""
    return offers.to_offer_read(await offers.get_offer(session, user, application_id))


@router.post("/{application_id}/offer/accept", responses=CONFLICT)
async def accept_offer(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> ApplicationRead:
    """offer_generated -> offer_accepted -> contract_generation -> e_sign:
    подготовка договора смоделирована и происходит сразу."""
    application = await offers.accept_offer(session, user, application_id)
    return await service.to_read(session, application)


@router.post("/{application_id}/offer/reject", responses=CONFLICT)
async def reject_offer(
    application_id: ApplicationId,
    body: RejectOfferRequest,
    user: CurrentClient,
    session: SessionDep,
) -> ApplicationRead:
    """offer_generated -> offer_rejected -> closed (close_reason = offer_rejected)."""
    application = await offers.reject_offer(session, user, application_id, body.reason)
    return await service.to_read(session, application)


@router.post("/{application_id}/sign", responses=CONFLICT)
async def sign_agreement(
    application_id: ApplicationId, body: SignRequest, user: CurrentClient, session: SessionDep
) -> ApplicationRead:
    """Смоделированное электронное подписание: e_sign -> disbursement -> completed.
    Код подтверждения не сверяется - в симуляции он показывается в интерфейсе."""
    application = await offers.sign_agreement(session, user, application_id)
    return await service.to_read(session, application)


@router.get("/{application_id}/contract")
async def get_contract(
    application_id: ApplicationId, user: CurrentClient, session: SessionDep
) -> LoanContractRead:
    """Кредитный договор и график платежей. Появляется после принятия оффера; до подписания -
    проект с плановыми датами, после выдачи - ссудный счёт и даты от фактической выдачи."""
    application = await service.get_client_application(session, user, application_id)
    contract = await loans.get_contract(session, application.id)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Договор ещё не сформирован")
    return await loans.to_contract_read(session, contract)
