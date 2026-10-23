import uuid

from fastapi import APIRouter, status

from app.api.deps import AUTH_RESPONSES, CONFLICT, NOT_FOUND, CurrentUser, not_implemented
from app.schemas.company import CompanyCreate, CompanyRead, CompanyRequisites, Inn
from app.services.companies import lookup_requisites

router = APIRouter(prefix="/companies", tags=["companies"], responses=AUTH_RESPONSES)


@router.get("/lookup", responses=NOT_FOUND)
async def lookup_company(inn: Inn, user: CurrentUser) -> CompanyRequisites:
    """Предзаполнение реквизитов по ИНН из (мока) ЕГРЮЛ/ЕГРИП.
    Демо-ИНН со сценариями - в docs/external-sources.md."""
    return await lookup_requisites(inn)


@router.post("", status_code=status.HTTP_201_CREATED, responses=CONFLICT)
async def create_company(body: CompanyCreate, user: CurrentUser) -> CompanyRead:
    """Привязать компанию к пользователю. Реквизиты берутся из реестра, а не из запроса."""
    not_implemented()


@router.get("")
async def list_my_companies(user: CurrentUser) -> list[CompanyRead]:
    not_implemented()


@router.get("/{company_id}", responses=NOT_FOUND)
async def get_company(company_id: uuid.UUID, user: CurrentUser) -> CompanyRead:
    not_implemented()
