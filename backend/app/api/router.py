from fastapi import APIRouter

from app.api.v1 import (
    applications,
    auth,
    backoffice,
    chat,
    companies,
    health,
    loans,
    notifications,
    products,
)

api_router = APIRouter(prefix="/api/v1")
for module in (
    health,
    auth,
    products,
    companies,
    applications,
    chat,
    loans,
    notifications,
    backoffice,
):
    api_router.include_router(module.router)
api_router.include_router(backoffice.employees_router)
