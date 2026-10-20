from fastapi import APIRouter

from app.api.v1 import applications, auth, backoffice, companies, health, notifications, products

api_router = APIRouter(prefix="/api/v1")
for module in (health, auth, products, companies, applications, notifications, backoffice):
    api_router.include_router(module.router)
