from fastapi import APIRouter

from app.api.deps import AUTH_RESPONSES, CurrentUser, not_implemented
from app.schemas.auth import CurrentUserRead, LoginRequest, TokenResponse
from app.schemas.common import ErrorResponse

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/login",
    responses={401: {"model": ErrorResponse, "description": "Неверный логин или пароль"}},
)
async def login(body: LoginRequest) -> TokenResponse:
    """Вход по тестовой учётной записи (клиент или сотрудник банка)."""
    not_implemented()


@router.get("/me", responses=AUTH_RESPONSES)
async def me(user: CurrentUser) -> CurrentUserRead:
    """Текущий пользователь и компании, от имени которых он действует."""
    not_implemented()
