from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import AUTH_RESPONSES, CurrentUser, SessionDep
from app.core.security import create_access_token, verify_password
from app.models import Company, CompanyMember, User
from app.schemas.auth import CurrentUserRead, LoginRequest, TokenResponse, UserCompany
from app.schemas.common import ErrorResponse

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/login",
    responses={401: {"model": ErrorResponse, "description": "Неверный логин или пароль"}},
)
async def login(body: LoginRequest, session: SessionDep) -> TokenResponse:
    """Вход по тестовой учётной записи (клиент или сотрудник банка)."""
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    token, ttl = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in=ttl)


@router.get("/me", responses=AUTH_RESPONSES)
async def me(user: CurrentUser, session: SessionDep) -> CurrentUserRead:
    """Текущий пользователь и компании, от имени которых он действует."""
    rows = await session.execute(
        select(CompanyMember.company_id, Company.name, CompanyMember.role)
        .join(Company, Company.id == CompanyMember.company_id)
        .where(CompanyMember.user_id == user.id)
        .order_by(Company.name)
    )
    return CurrentUserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        role=user.role,
        companies=[
            UserCompany(company_id=company_id, company_name=name, role=role)
            for company_id, name, role in rows
        ],
    )
