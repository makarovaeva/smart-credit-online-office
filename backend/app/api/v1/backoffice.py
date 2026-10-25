import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse

from app.api.deps import (
    AUTH_RESPONSES,
    CONFLICT,
    NOT_FOUND,
    CurrentAnalyst,
    CurrentEmployee,
    CurrentUnderwriter,
    Limit,
    Offset,
    SessionDep,
    file_response,
)
from app.models.enums import ApplicationStatus, RiskZone
from app.schemas.backoffice import (
    AssignRequest,
    BackofficeApplicationDetail,
    BackofficeApplicationItem,
    InternalRequestRead,
    ReturnRequestBody,
)
from app.schemas.common import Page
from app.schemas.decision import (
    AnalystConclusionRequest,
    CreditMemoRead,
    DecisionRead,
    UnderwriterDecisionRequest,
)
from app.schemas.document import InfoRequestCreate, InfoRequestRead
from app.schemas.loan import LoanContractRead
from app.services import backoffice, decisions, documents, internal_requests, loans, offers
from app.services.offers import to_decision_read

router = APIRouter(
    prefix="/backoffice/applications", tags=["backoffice"], responses=AUTH_RESPONSES | NOT_FOUND
)


@router.get("")
async def list_applications(
    employee: CurrentEmployee,
    session: SessionDep,
    status_in: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    risk_zone: RiskZone | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[BackofficeApplicationItem]:
    """Свои заявки сотрудника, старые первыми: назначенные на него и те, с которыми он уже
    работал. Заявка назначается автоматически: на analyst_escalation - аналитику,
    на underwriter_review - андеррайтеру. Текущая очередь аналитика - status=analyst_escalation,
    андеррайтера - status=underwriter_review. Администратор видит все заявки."""
    items, total = await backoffice.list_queue(
        session, employee, statuses=status_in, risk_zone=risk_zone, limit=limit, offset=offset
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{application_id}")
async def get_application(
    application_id: uuid.UUID, employee: CurrentEmployee, session: SessionDep
) -> BackofficeApplicationDetail:
    """Карточка своей заявки: данные, проверки, метрики, скоринг, AI Credit Memo, история."""
    return await backoffice.get_detail(session, employee, application_id)


@router.post("/{application_id}/assign", responses=CONFLICT)
async def assign(
    application_id: uuid.UUID, body: AssignRequest, employee: CurrentEmployee, session: SessionDep
) -> BackofficeApplicationDetail:
    """Передать заявку другому сотруднику той же роли. Доступно сотруднику текущего этапа
    и администратору."""
    return await backoffice.reassign(session, employee, application_id, body.assignee_id)


@router.post("/{application_id}/analyst-conclusion", responses=CONFLICT)
async def complete_analysis(
    application_id: uuid.UUID,
    body: AnalystConclusionRequest,
    analyst: CurrentAnalyst,
    session: SessionDep,
) -> CreditMemoRead:
    """Заключение кредитного аналитика дописывается в AI Credit Memo (или обновляется
    по запросу андеррайтера): analyst_escalation -> analyst_completed -> underwriter_review."""
    memo = await decisions.complete_analysis(session, analyst, application_id, body)
    return CreditMemoRead.model_validate(memo)


@router.post("/{application_id}/decision", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def make_decision(
    application_id: uuid.UUID,
    body: UnderwriterDecisionRequest,
    underwriter: CurrentUnderwriter,
    session: SessionDep,
) -> DecisionRead:
    """Финальное решение андеррайтера по AI Credit Memo и/или заключению аналитика:
    approved / conditional_approval (контр-предложение) -> offer_generated,
    more_information_required + client -> need_additional_data (дозапрос формирует ИИ),
    more_information_required + credit_analyst -> analyst_escalation,
    declined -> closed."""
    decision = await decisions.make_decision(session, underwriter, application_id, body)
    return to_decision_read(decision)


@router.post(
    "/{application_id}/info-requests", status_code=status.HTTP_201_CREATED, responses=CONFLICT
)
async def request_documents(
    application_id: uuid.UUID, body: InfoRequestCreate, analyst: CurrentAnalyst, session: SessionDep
) -> InfoRequestRead:
    """Аналитик запрашивает документы у клиента через ИИ-агента:
    analyst_escalation -> need_additional_data. Когда клиент ответит, заявка вернётся
    к аналитику (analyst_escalation). Андеррайтер запрашивает документы решением
    more_information_required."""
    request = await documents.request_documents_by_analyst(session, analyst, application_id, body)
    return InfoRequestRead.model_validate(request)


# --- Запрос экспертизы андеррайтера у аналитика ---

RequestId = uuid.UUID


@router.post("/{application_id}/internal-requests/{request_id}/accept", responses=CONFLICT)
async def accept_expertise_request(
    application_id: uuid.UUID, request_id: RequestId, analyst: CurrentAnalyst, session: SessionDep
) -> InternalRequestRead:
    """Аналитик принимает запрос экспертизы в работу (open -> accepted). Закрывает его
    заключение (analyst-conclusion) или возврат андеррайтеру."""
    request = await internal_requests.accept(session, analyst, application_id, request_id)
    return InternalRequestRead.model_validate(request)


@router.post("/{application_id}/internal-requests/{request_id}/return", responses=CONFLICT)
async def return_expertise_request(
    application_id: uuid.UUID,
    request_id: RequestId,
    body: ReturnRequestBody,
    analyst: CurrentAnalyst,
    session: SessionDep,
) -> InternalRequestRead:
    """Вернуть запрос андеррайтеру с комментарием, без заключения:
    analyst_escalation -> underwriter_review, андеррайтер получает уведомление."""
    request = await internal_requests.return_request(
        session, analyst, application_id, request_id, body.comment
    )
    return InternalRequestRead.model_validate(request)


@router.post("/{application_id}/internal-requests/{request_id}/cancel", responses=CONFLICT)
async def cancel_expertise_request(
    application_id: uuid.UUID,
    request_id: RequestId,
    underwriter: CurrentUnderwriter,
    session: SessionDep,
) -> InternalRequestRead:
    """Андеррайтер отзывает свой запрос экспертизы: analyst_escalation -> underwriter_review."""
    request = await internal_requests.cancel_request(
        session, underwriter, application_id, request_id
    )
    return InternalRequestRead.model_validate(request)


@router.post("/{application_id}/internal-requests/{request_id}/remind", responses=CONFLICT)
async def remind_analyst(
    application_id: uuid.UUID,
    request_id: RequestId,
    underwriter: CurrentUnderwriter,
    session: SessionDep,
) -> InternalRequestRead:
    """Напомнить аналитику о запросе экспертизы (уведомление в кабинете)."""
    request = await internal_requests.remind_analyst(
        session, underwriter, application_id, request_id
    )
    return InternalRequestRead.model_validate(request)


# --- Дозапросы клиенту от сотрудников ---


@router.post("/{application_id}/info-requests/{request_id}/cancel", responses=CONFLICT)
async def cancel_info_request(
    application_id: uuid.UUID, request_id: RequestId, employee: CurrentEmployee, session: SessionDep
) -> InfoRequestRead:
    """Отозвать свой дозапрос клиенту (аналитик или андеррайтер - инициатор). Если открытых
    дозапросов не осталось, заявка возвращается к инициатору."""
    request = await internal_requests.cancel_info_request(
        session, employee, application_id, request_id
    )
    return InfoRequestRead.model_validate(request)


@router.post("/{application_id}/info-requests/{request_id}/remind", responses=CONFLICT)
async def remind_client(
    application_id: uuid.UUID, request_id: RequestId, employee: CurrentEmployee, session: SessionDep
) -> InfoRequestRead:
    """Напомнить клиенту о дозапросе через ИИ-агента: сообщение в чате и уведомление."""
    request = await internal_requests.remind_client(session, employee, application_id, request_id)
    return InfoRequestRead.model_validate(request)


@router.get(
    "/{application_id}/documents/{document_id}/content",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_document(
    application_id: uuid.UUID,
    document_id: uuid.UUID,
    employee: CurrentEmployee,
    session: SessionDep,
) -> FileResponse:
    """Скачать файл документа своей заявки (список - в карточке заявки)."""
    document, path = await documents.get_employee_document(
        session, employee, application_id, document_id
    )
    return file_response(document, path)


@router.post("/{application_id}/contract", responses=CONFLICT)
async def prepare_contract(
    application_id: uuid.UUID, analyst: CurrentAnalyst, session: SessionDep
) -> LoanContractRead:
    """Подготовка кредитного договора аналитиком после принятия оффера:
    contract_generation -> e_sign. Нужна при CONTRACT_PREPARATION=analyst; в режиме auto
    договор готовится сразу при принятии оффера. Повторный вызов возвращает тот же договор."""
    contract = await offers.prepare_contract_by_analyst(session, analyst, application_id)
    return await loans.to_contract_read(session, contract)
