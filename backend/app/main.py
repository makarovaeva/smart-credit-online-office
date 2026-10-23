from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError

from app.api.router import api_router
from app.core.config import get_settings
from app.services.errors import DomainError
from app.services.status_machine import TransitionError


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


async def transition_error_handler(request: Request, exc: TransitionError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


async def stale_data_handler(request: Request, exc: StaleDataError) -> JSONResponse:
    return JSONResponse({"detail": "Заявка изменена параллельно, обновите данные"}, status_code=409)


DESCRIPTION = """
Умный кредитный кабинет предпринимателя (Альфа-Хак 2026): кредитный конвейер для МСБ
от заявки до выдачи.

Авторизация: `Authorization: Bearer <JWT>`. Клиент получает токен через
`POST /api/v1/auth/login/phone`, сотрудник банка - через `POST /api/v1/auth/login`.
Демо-учётки - в README репозитория.

Деньги - строкой (`"1500000.00"`), даты - ISO 8601. Ошибки - `{"detail": "..."}`:
404 - объекта нет или нет доступа, 409 - действие недопустимо в текущем статусе,
422 - данные не проходят правила.
"""

TAGS = [
    {"name": "health", "description": "Проверка живости и готовности (БД)"},
    {"name": "auth", "description": "Вход клиента по телефону и сотрудника по логину и паролю"},
    {"name": "products", "description": "Каталог кредитных продуктов"},
    {"name": "companies", "description": "Компании заёмщиков, реквизиты из ЕГРЮЛ/ЕГРИП"},
    {"name": "applications", "description": "Заявка клиента: черновик, согласия, подача, оффер"},
    {"name": "loans", "description": "Договоры и кредиты клиента, график платежей"},
    {"name": "notifications", "description": "Уведомления в кабинете"},
    {"name": "backoffice", "description": "Рабочее место аналитика и андеррайтера"},
]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=DESCRIPTION.strip(),
        openapi_tags=TAGS,
        debug=settings.debug,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(TransitionError, transition_error_handler)
    app.add_exception_handler(StaleDataError, stale_data_handler)
    app.include_router(api_router)
    return app


app = create_app()
