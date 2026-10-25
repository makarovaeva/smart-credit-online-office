import uuid

from fastapi import APIRouter, status

from app.api.deps import AUTH_RESPONSES, CONFLICT, NOT_FOUND, CurrentClient, CurrentUser, SessionDep
from app.schemas.company import CompanyCreate, CompanyRead, CompanyRequisites, Inn
from app.services import companies

router = APIRouter(prefix="/companies", tags=["companies"], responses=AUTH_RESPONSES)


@router.get("/lookup", responses=NOT_FOUND)
async def lookup_company(inn: Inn, user: CurrentUser) -> CompanyRequisites:
    """Предзаполнение реквизитов, руководителя и учредителей по ИНН из (мока) ЕГРЮЛ/ЕГРИП.
    Демо-ИНН со сценариями - в docs/external-sources.md."""
    return await companies.lookup_requisites(inn)


@router.post("", status_code=status.HTTP_201_CREATED, responses=CONFLICT | NOT_FOUND)
async def create_company(
    body: CompanyCreate, user: CurrentClient, session: SessionDep
) -> CompanyRead:
    """Привязать компанию к пользователю. Реквизиты берутся из реестра, а не из запроса.
    Компания, уже обслуживаемая в банке, повторно не привязывается (409)."""
    return await companies.link_company(session, user, body)


@router.get("")
async def list_my_companies(user: CurrentClient, session: SessionDep) -> list[CompanyRead]:
    """Компании, от имени которых действует пользователь, с ролью в каждой."""
    return await companies.list_companies(session, user)


@router.get("/{company_id}", responses=NOT_FOUND)
async def get_company(
    company_id: uuid.UUID, user: CurrentClient, session: SessionDep
) -> CompanyRead:
    """Профиль компании: организация, деятельность, руководитель и владельцы, право подписи,
    контакты и расчётный счёт. Чужая компания - 404."""
    return await companies.get_company(session, user, company_id)
