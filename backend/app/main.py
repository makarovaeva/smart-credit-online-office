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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
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
