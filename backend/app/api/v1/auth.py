from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import AUTH_RESPONSES, CurrentUser, SessionDep
from app.core.security import create_access_token, verify_password
from app.models import Company, CompanyMember, User
from app.models.enums import UserRole
from app.schemas.auth import (
    CurrentUserRead,
    LoginRequest,
    PhoneLoginRequest,
    TokenResponse,
    UserCompany,
)
from app.schemas.common import ErrorResponse

router = APIRouter(tags=["auth"])

EMPLOYEE_ROLES = frozenset({UserRole.CREDIT_ANALYST, UserRole.UNDERWRITER, UserRole.ADMIN})


def _token(user: User) -> TokenResponse:
    token, ttl = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in=ttl)


@router.post(
    "/auth/login",
    responses={401: {"model": ErrorResponse, "description": "Неверный логин или пароль"}},
)
async def login(body: LoginRequest, session: SessionDep) -> TokenResponse:
    """Вход сотрудника банка (кредитный аналитик, андеррайтер) по логину и паролю.
    Учётные записи заведены заранее, регистрации нет. Клиенты входят по телефону."""
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if (
        user is None
        or not user.is_active
        or user.role not in EMPLOYEE_ROLES
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return _token(user)


@router.post(
    "/auth/login/phone",
    responses={401: {"model": ErrorResponse, "description": "Клиент с таким номером не найден"}},
)
async def login_by_phone(body: PhoneLoginRequest, session: SessionDep) -> TokenResponse:
    """Упрощённый вход клиента по номеру телефона, без пароля и SMS: по условиям кейса
    пользователь уже клиент банка. Демо-номера - в README."""
    user = await session.scalar(
        select(User).where(User.phone == body.phone, User.role == UserRole.CLIENT)
    )
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Клиент с таким номером не найден")
    return _token(user)


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
