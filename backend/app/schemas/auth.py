import uuid

from pydantic import BaseModel, EmailStr

from app.models.enums import CompanyMemberRole, UserRole
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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
