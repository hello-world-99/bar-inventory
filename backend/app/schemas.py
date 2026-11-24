from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import Role


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORM):
    id: int
    username: str
    full_name: str
    role: Role
    is_active: bool
    permissions: list[str] = []


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    full_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.staff


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class SettingsOut(ORM):
    venue_name: str
    currency: str
    currency_decimals: int
    timezone: str
    business_day_starts_at: time
    blind_count: bool


class SettingsUpdate(BaseModel):
    venue_name: str | None = Field(default=None, min_length=1, max_length=128)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    # Prices are NUMERIC(14,2), so more than 2 display decimals would be meaningless.
    currency_decimals: int | None = Field(default=None, ge=0, le=2)
    timezone: str | None = None
    business_day_starts_at: time | None = None
    blind_count: bool | None = None

    @field_validator("timezone")
    @classmethod
    def valid_tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError("Unknown time zone") from e
        return v
