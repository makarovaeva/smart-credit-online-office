from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.schemas.common import ErrorResponse

bearer_scheme = HTTPBearer(description="JWT из POST /api/v1/auth/login")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> HTTPAuthorizationCredentials:
    # TODO: декодировать JWT и вернуть User
    return credentials


async def require_employee(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(get_current_user)],
) -> HTTPAuthorizationCredentials:
    # TODO: проверить роль credit_analyst/underwriter/admin
    return credentials


async def require_analyst(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(get_current_user)],
) -> HTTPAuthorizationCredentials:
    # TODO: проверить роль credit_analyst
    return credentials


async def require_underwriter(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(get_current_user)],
) -> HTTPAuthorizationCredentials:
    # TODO: проверить роль underwriter
    return credentials


CurrentUser = Annotated[HTTPAuthorizationCredentials, Depends(get_current_user)]
CurrentEmployee = Annotated[HTTPAuthorizationCredentials, Depends(require_employee)]
CurrentAnalyst = Annotated[HTTPAuthorizationCredentials, Depends(require_analyst)]
CurrentUnderwriter = Annotated[HTTPAuthorizationCredentials, Depends(require_underwriter)]

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

AUTH_RESPONSES: dict[int | str, dict] = {
    401: {"model": ErrorResponse, "description": "Нет или невалидный токен"},
    403: {"model": ErrorResponse, "description": "Недостаточно прав"},
}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Объект не найден"}}
CONFLICT = {
    409: {
        "model": ErrorResponse,
        "description": "Действие недопустимо в текущем статусе заявки или версия устарела",
    }
}


def not_implemented() -> NoReturn:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Not implemented yet")
