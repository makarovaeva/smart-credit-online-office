import re
import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import CompanyMemberRole, UserRole
from app.schemas.common import ORMModel


def normalize_phone(value: str) -> str:
    """Российский номер в виде +7XXXXXXXXXX: «8 (999) 123-45-67» и «+7 999 1234567» совпадут."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("Нужен российский номер телефона из 10 цифр после +7")
    return f"+7{digits}"


class LoginRequest(BaseModel):
    """Вход сотрудника банка: логин - рабочий email."""

    email: EmailStr
    password: str


class PhoneLoginRequest(BaseModel):
    """Упрощённый вход клиента: он уже клиент банка, номер привязан к учётной записи."""

    phone: str = Field(examples=["+7 999 000-00-01"])

    @field_validator("phone")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_phone(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserCompany(ORMModel):
    company_id: uuid.UUID
    company_name: str
    role: CompanyMemberRole


class CurrentUserRead(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    phone: str | None
    role: UserRole
    companies: list[UserCompany]
