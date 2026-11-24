from datetime import time

from sqlalchemy import Boolean, CheckConstraint, Integer, SmallInteger, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSettings(Base):
    """Single-row installation settings (id is always 1)."""

    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("id = 1", name="settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    venue_name: Mapped[str] = mapped_column(String(128), default="My Bar")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    currency_decimals: Mapped[int] = mapped_column(SmallInteger, default=2)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    business_day_starts_at: Mapped[time] = mapped_column(Time, default=time(6, 0))
    # Hide expected quantities in the count form. A hint for honesty, not a security control.
    blind_count: Mapped[bool] = mapped_column(Boolean, default=False)
