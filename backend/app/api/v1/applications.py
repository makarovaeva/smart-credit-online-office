import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    AUTH_RESPONSES,
    CONFLICT,
    NOT_FOUND,
    CurrentUser,
    Limit,
    Offset,
    not_implemented,
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

router = APIRouter(
    prefix="/applications", tags=["applications"], responses=AUTH_RESPONSES | NOT_FOUND
)

ApplicationId = uuid.UUID


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_application(body: ApplicationCreate, user: CurrentUser) -> ApplicationRead:
    """Создать черновик заявки."""
    not_implemented()


@router.get("")
async def list_applications(
    user: CurrentUser,
    status_in: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
    company_id: uuid.UUID | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[ApplicationShort]:
    """Заявки компаний пользователя, новые первыми."""
    not_implemented()


@router.get("/{application_id}")
async def get_application(application_id: ApplicationId, user: CurrentUser) -> ApplicationRead:
    """Заявка с понятным описанием этапа и списком доступных действий."""
    not_implemented()


@router.patch("/{application_id}", responses=CONFLICT)
async def update_application(
    application_id: ApplicationId, body: ApplicationUpdate, user: CurrentUser
) -> ApplicationRead:
    """Изменить черновик или дополнить данные по дозапросу."""
    not_implemented()


# --- Согласия и предварительный лимит ---


@router.post("/{application_id}/consents", responses=CONFLICT)
async def give_consents(
    application_id: ApplicationId, body: ConsentsRequest, user: CurrentUser
) -> ApplicationRead:
    """Дать согласия на получение данных (БКИ, ФНС, цифровой профиль).
    draft -> data_collection: ИИ собирает данные и рассчитывает предварительный лимит."""
    not_implemented()


@router.get("/{application_id}/consents")
async def list_consents(application_id: ApplicationId, user: CurrentUser) -> list[ConsentRead]:
    not_implemented()


@router.get("/{application_id}/pre-approval")
async def get_pre_approval(application_id: ApplicationId, user: CurrentUser) -> PreApprovalRead:
    """Вероятность одобрения, диапазон суммы, прогнозируемая ставка,
    необходимость обеспечения и рекомендации."""
    not_implemented()


@router.post("/{application_id}/pre-approval/decline", responses=CONFLICT)
async def decline_pre_approval(application_id: ApplicationId, user: CurrentUser) -> ApplicationRead:
    """Клиент не продолжает после предварительного расчёта: pre_approved -> closed
    (close_reason = pre_approval_declined)."""
    not_implemented()


@router.post("/{application_id}/submit", responses=CONFLICT)
async def submit_application(application_id: ApplicationId, user: CurrentUser) -> ApplicationRead:
    """Подтвердить сумму, срок, цель и согласие на проверки: pre_approved -> submitted.
    Запускает анализ ИИ."""
    not_implemented()


@router.get("/{application_id}/history")
async def get_history(application_id: ApplicationId, user: CurrentUser) -> list[StatusHistoryItem]:
    """Таймлайн заявки."""
    not_implemented()


# --- Документы ---


@router.post("/{application_id}/documents", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def upload_document(
    application_id: ApplicationId,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    type: Annotated[DocumentType, Form()],
    info_request_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentRead:
    not_implemented()


@router.get("/{application_id}/documents")
async def list_documents(application_id: ApplicationId, user: CurrentUser) -> list[DocumentRead]:
    not_implemented()


@router.get(
    "/{application_id}/documents/{document_id}/content",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_document(
    application_id: ApplicationId, document_id: uuid.UUID, user: CurrentUser
) -> StreamingResponse:
    not_implemented()


@router.delete(
    "/{application_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_document(
    application_id: ApplicationId, document_id: uuid.UUID, user: CurrentUser
) -> None:
    not_implemented()


# --- Дозапросы ---


@router.get("/{application_id}/info-requests")
async def list_info_requests(
    application_id: ApplicationId, user: CurrentUser
) -> list[InfoRequestRead]:
    not_implemented()


@router.post("/{application_id}/info-requests/{info_request_id}/answer", responses=CONFLICT)
async def answer_info_request(
    application_id: ApplicationId,
    info_request_id: uuid.UUID,
    body: InfoRequestAnswer,
    user: CurrentUser,
) -> InfoRequestRead:
    """Ответить на дозапрос. Когда закрыты все открытые дозапросы:
    дозапрос ИИ - need_additional_data -> ai_verification (повторная проверка комплекта),
    дозапрос андеррайтера - need_additional_data -> underwriter_review."""
    not_implemented()


# --- Оффер и выдача ---


@router.get("/{application_id}/offer")
async def get_offer(application_id: ApplicationId, user: CurrentUser) -> OfferRead:
    """Оффер: сумма, ставка, срок, условия и причины решения.
    decision_type = conditional_approval - контр-предложение на изменённых условиях."""
    not_implemented()


@router.post("/{application_id}/offer/accept", responses=CONFLICT)
async def accept_offer(application_id: ApplicationId, user: CurrentUser) -> ApplicationRead:
    """offer_generated -> offer_accepted; далее система готовит документы на подпись."""
    not_implemented()


@router.post("/{application_id}/offer/reject", responses=CONFLICT)
async def reject_offer(
    application_id: ApplicationId, body: RejectOfferRequest, user: CurrentUser
) -> ApplicationRead:
    """offer_generated -> offer_rejected -> closed (close_reason = offer_rejected)."""
    not_implemented()


@router.post("/{application_id}/sign", responses=CONFLICT)
async def sign_agreement(
    application_id: ApplicationId, body: SignRequest, user: CurrentUser
) -> ApplicationRead:
    """Смоделированное электронное подписание: e_sign -> disbursement -> completed."""
    not_implemented()
