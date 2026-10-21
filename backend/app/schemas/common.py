from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Денежные суммы в JSON сериализуются строкой, чтобы не терять точность
MoneyAmount = Annotated[
    Decimal, Field(gt=0, max_digits=15, decimal_places=2, examples=["1500000.00"])
]
TermMonths = Annotated[int, Field(ge=1, le=120, examples=[24])]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["transition draft -> completed is not allowed"])
