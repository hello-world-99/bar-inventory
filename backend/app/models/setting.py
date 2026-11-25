from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Numeric, SmallInteger, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSettings(Base):
    """Single-row installation settings (id is always 1)."""

    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("id = 1", name="settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    venue_name: Mapped[str] = mapped_column(String(128), default="My Bar")
    # Money is stored in won; this is the DISPLAY currency (KRW, or USD at usd_krw_rate). Decimals follow it.
    currency: Mapped[str] = mapped_column(String(3), default="KRW")
    currency_decimals: Mapped[int] = mapped_column(SmallInteger, default=0)
    usd_krw_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # won per dollar
    rate_mode: Mapped[str] = mapped_column(String(8), default="auto")  # auto: fetched daily (app/services/fx.py)
    rate_source: Mapped[str | None] = mapped_column(String(64))
    rate_date: Mapped[str | None] = mapped_column(String(10))
    rate_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate_error: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    business_day_starts_at: Mapped[time] = mapped_column(Time, default=time(6, 0))
    # Hide expected quantities in the count form. A hint for honesty, not a security control.
    blind_count: Mapped[bool] = mapped_column(Boolean, default=False)
