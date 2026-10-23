import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

# Деньги храним с копейками, до триллиона
Money = Numeric(15, 2)


def str_enum(enum_cls: type[StrEnum], *, check: bool = True, name: str | None = None) -> Enum:
    """varchar + CHECK вместо нативного enum Postgres: новые значения не требуют ALTER TYPE.

    check=False для элементов ARRAY: Postgres не умеет CHECK IN по массиву.
    name нужен, если в таблице несколько колонок одного enum: из него строится имя CHECK.
    """
    return Enum(
        enum_cls,
        name=name or enum_cls.__name__.lower(),
        native_enum=False,
        create_constraint=check,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class UUIDPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


def utcnow() -> datetime:
    return datetime.now(UTC)


# Время ставится в Python: значение доступно сразу после flush без повторного SELECT
# (в async ленивая догрузка невозможна), а несколько записей одной транзакции
# упорядочиваются - now() в Postgres одинаков на всю транзакцию.
class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), onupdate=utcnow
    )
