from pathlib import Path
from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_session
from app.models import Document, User
from app.models.enums import UserRole
from app.schemas.common import ErrorResponse

bearer_scheme = HTTPBearer(description="JWT из POST /api/v1/auth/login", auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Нет или невалидный токен",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise unauthorized from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    async def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return dependency


CurrentClient = Annotated[User, Depends(require_roles(UserRole.CLIENT))]
CurrentEmployee = Annotated[
    User,
    Depends(require_roles(UserRole.CREDIT_ANALYST, UserRole.UNDERWRITER, UserRole.ADMIN)),
]
CurrentAnalyst = Annotated[User, Depends(require_roles(UserRole.CREDIT_ANALYST))]
CurrentUnderwriter = Annotated[User, Depends(require_roles(UserRole.UNDERWRITER))]

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


def file_response(document: Document, path: Path) -> FileResponse:
    """Скачивание документа с исходным именем файла (Content-Disposition: attachment)."""
    return FileResponse(path, media_type=document.content_type, filename=document.file_name)


def not_implemented() -> NoReturn:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Not implemented yet")
