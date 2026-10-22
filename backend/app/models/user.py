from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UserRole
from app.models.mixins import TimestampMixin, UUIDPkMixin, str_enum


class User(UUIDPkMixin, TimestampMixin, Base):
    """Учётная запись: представитель бизнеса или сотрудник банка."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    # +7XXXXXXXXXX; клиенты входят по номеру телефона
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole))
    is_active: Mapped[bool] = mapped_column(default=True)
