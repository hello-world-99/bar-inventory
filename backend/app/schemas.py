from datetime import datetime, time
from decimal import Decimal
from typing import Literal
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
    currency: Literal["KRW", "USD"]  # display currency; money is stored in won
    currency_decimals: int
    timezone: str
    business_day_starts_at: time
    blind_count: bool
    usd_krw_rate: Decimal | None
    rate_mode: Literal["auto", "manual"]
    rate_source: str | None
    rate_date: str | None
    rate_updated_at: datetime | None
    rate_checked_at: datetime | None
    rate_error: str | None


class SettingsUpdate(BaseModel):
    venue_name: str | None = Field(default=None, min_length=1, max_length=128)
    currency: Literal["KRW", "USD"] | None = None  # decimals follow: KRW 0, USD 2
    rate_mode: Literal["auto", "manual"] | None = None
    usd_krw_rate: Decimal | None = Field(default=None, ge=100, le=100000, max_digits=12, decimal_places=4)  # manual mode
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
