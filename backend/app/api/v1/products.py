import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import NOT_FOUND, SessionDep
from app.models import CreditProduct
from app.schemas.product import ProductMatch, ProductMatchRequest, ProductRead
from app.services.products import match

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
async def list_products(session: SessionDep) -> list[ProductRead]:
    """Каталог активных кредитных продуктов."""
    products = await session.scalars(
        select(CreditProduct).where(CreditProduct.is_active).order_by(CreditProduct.min_amount)
    )
    return [ProductRead.model_validate(p) for p in products]


@router.get("/{product_id}", responses=NOT_FOUND)
async def get_product(product_id: uuid.UUID, session: SessionDep) -> ProductRead:
    product = await session.get(CreditProduct, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Продукт не найден")
    return ProductRead.model_validate(product)


@router.post("/match")
async def match_products(body: ProductMatchRequest, session: SessionDep) -> list[ProductMatch]:
    """Подбор продуктов под потребность: подходящие первыми, с пояснениями и примерным платежом
    (аннуитет по базовой ставке на условиях, ближайших к запрошенным в рамках продукта)."""
    return await match(session, body)
