import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class InventoryStatus(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class Inventory(Base):
    __tablename__ = "inventories"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[InventoryStatus] = mapped_column(
        Enum(InventoryStatus, name="inventory_status"), default=InventoryStatus.in_progress
    )
    comment: Mapped[str] = mapped_column(Text, default="")
    started_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Who/when CLOSED the inventory: completion for status=completed, cancellation for status=cancelled.
    # API exposes them as closed_by/closed_at so a cancelled count never reads as "completed".
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The single carrier of the inventory <-> adjustment document link.
    adjustment_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_documents.id"), unique=True)

    lines: Mapped[list["InventoryLine"]] = relationship(back_populates="inventory", cascade="all, delete-orphan")


class InventoryLine(Base):
    __tablename__ = "inventory_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inventory_id: Mapped[int] = mapped_column(ForeignKey("inventories.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    # Balance when the inventory started (or when the line was added). Report only.
    expected_at_start_base: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    counted_base: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    # Balance reconstructed for the moment of counting; delta = counted - this.
    expected_at_count_base: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # Price snapshot taken on completion.
    unit_cost_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    version: Mapped[int] = mapped_column(Integer, default=1)

    inventory: Mapped[Inventory] = relationship(back_populates="lines")
