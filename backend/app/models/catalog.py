import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Unit(str, enum.Enum):
    """Unit of a product as named in the requirements: purchase, price and default display unit."""

    pcs = "pcs"
    bottle = "bottle"
    l = "l"  # noqa: E741
    ml = "ml"
    kg = "kg"
    g = "g"


class BaseUnit(str, enum.Enum):
    """Storage unit of every quantity (qty_base)."""

    ml = "ml"
    g = "g"
    pcs = "pcs"


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    # i18n key for seeded categories (alcohol, soft_drinks, ...); NULL for user-defined ones.
    code: Mapped[str | None] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    sku: Mapped[str] = mapped_column(String(64))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    unit: Mapped[Unit] = mapped_column(Enum(Unit, name="product_unit"))
    base_unit: Mapped[BaseUnit] = mapped_column(Enum(BaseUnit, name="base_unit"))
    unit_size: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    min_stock_base: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    barcode: Mapped[str | None] = mapped_column(String(64))
    full_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    empty_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category: Mapped[Category] = relationship()
