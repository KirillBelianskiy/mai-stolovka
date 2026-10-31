from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from user_service.application.passwords import normalize_login
from user_service.domain.users import Role


class TelegramLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    init_data: str = Field(min_length=1, max_length=16384)


class StaffLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return normalize_login(value)


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    telegram_id: int | None
    username: str | None
    full_name: str
    role: Role
    created_at: datetime


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile
