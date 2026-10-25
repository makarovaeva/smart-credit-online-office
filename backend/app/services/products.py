"""Подбор кредитного продукта под потребность клиента без банковской экспертизы."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditProduct
from app.schemas.product import ProductMatch, ProductMatchRequest, ProductRead
from app.services.chat_events import rub
from app.services.schedule import annuity_payment

PURPOSE_NAMES = {
    "working_capital": "пополнение оборотных средств",
    "equipment": "покупку оборудования",
    "business_expansion": "развитие бизнеса",
    "refinancing": "рефинансирование",
    "other": "эту цель",
}


def _evaluate(product: CreditProduct, body: ProductMatchRequest) -> ProductMatch:
    notes, fits = [], True
    if body.purpose not in product.purposes:
        fits = False
        notes.append(f"Продукт не предназначен на {PURPOSE_NAMES[body.purpose]}")
    if body.credit_format is not None and body.credit_format != product.credit_format:
        fits = False
        notes.append("Другой формат кредита")
    if body.amount < product.min_amount:
        fits = False
        notes.append(f"Минимальная сумма - {rub(product.min_amount)}")
    elif body.amount > product.max_amount:
        fits = False
        notes.append(f"Максимальная сумма - {rub(product.max_amount)}: уменьшите сумму")
    if body.term_months < product.min_term_months:
        fits = False
        notes.append(f"Минимальный срок - {product.min_term_months} мес.")
    elif body.term_months > product.max_term_months:
        fits = False
        notes.append(f"Максимальный срок - {product.max_term_months} мес.")
    if product.requires_collateral and not body.has_collateral:
        fits = False
        notes.append("Нужен залог")
    if fits:
        notes.append("Подходит по цели, сумме и сроку")
    # Платёж - на ближайших к запросу условиях в рамках продукта
    amount = min(max(body.amount, product.min_amount), product.max_amount)
    term = min(max(body.term_months, product.min_term_months), product.max_term_months)
    return ProductMatch(
        product=ProductRead.model_validate(product),
        fits=fits,
        notes=notes,
        estimated_rate=product.base_rate,
        estimated_monthly_payment=annuity_payment(amount, term, product.base_rate),
    )


async def match(session: AsyncSession, body: ProductMatchRequest) -> list[ProductMatch]:
    """Подходящие продукты первыми, внутри - по ставке."""
    products = await session.scalars(select(CreditProduct).where(CreditProduct.is_active))
    results = [_evaluate(p, body) for p in products]
    return sorted(results, key=lambda m: (not m.fits, m.estimated_rate, m.product.min_amount))
