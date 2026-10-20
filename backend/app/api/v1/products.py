import uuid

from fastapi import APIRouter

from app.api.deps import NOT_FOUND, not_implemented
from app.schemas.product import ProductMatch, ProductMatchRequest, ProductRead

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
async def list_products() -> list[ProductRead]:
    """Каталог активных кредитных продуктов."""
    not_implemented()


@router.get("/{product_id}", responses=NOT_FOUND)
async def get_product(product_id: uuid.UUID) -> ProductRead:
    not_implemented()


@router.post("/match")
async def match_products(body: ProductMatchRequest) -> list[ProductMatch]:
    """Подбор продуктов под потребность: подходящие первыми, с пояснениями и примерным платежом."""
    not_implemented()
