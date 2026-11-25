"""POS sales imports and kitchen norms (agent-room replies 30-32).

A daily sales report exported from the POS (xlsx) is stored as a sales import. Each POS item (keyed by the POS
code) may have a norm: the catalog products one sold unit consumes. Posting an import writes the computed usage
off the stock as an ordinary write-off with reason 'sales'.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PosItem(Base):
    __tablename__ = "pos_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))  # as last seen in a POS report
    # Drinks and other items that never consume kitchen stock: hidden from the "no norm" list.
    not_kitchen: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    components: Mapped[list["PosItemComponent"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="PosItemComponent.product_id"
    )


class PosItemComponent(Base):
    """Norm: one sold unit of the POS item consumes qty_base of the product."""

    __tablename__ = "pos_item_components"

    pos_item_id: Mapped[int] = mapped_column(ForeignKey("pos_items.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    qty_base: Mapped[Decimal] = mapped_column(Numeric(14, 3))

    item: Mapped[PosItem] = relationship(back_populates="components")


class SalesImportStatus(str, enum.Enum):
    draft = "draft"  # uploaded, usage computed from the current norms
    posted = "posted"  # written off; usage frozen in sales_import_usage
    covered = "covered"  # completed inventories already counted ALL of this stock; kept for history, no document
    voided = "voided"  # cancelled (a posted one through a reversal); the day can be imported again


class SalesImport(Base):
    __tablename__ = "sales_imports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)  # client-generated: retried uploads are idempotent
    sales_date: Mapped[date] = mapped_column(Date)  # business day of the sales
    file_name: Mapped[str] = mapped_column(String(255), default="")
    file_sha256: Mapped[str] = mapped_column(String(64))  # informational: re-exports of the same day differ in bytes
    # sha256 of the normalized rows: the same sales under another date are rejected (reply 32, P1).
    content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[SalesImportStatus] = mapped_column(Enum(SalesImportStatus, name="sales_import_status"), default=SalesImportStatus.draft)
    total_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    total_revenue: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))  # set when posted or covered
    write_off_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_documents.id"), unique=True)
    covered_inventory_id: Mapped[int | None] = mapped_column(ForeignKey("inventories.id"))  # first covering inventory
    post_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    prepared_by: Mapped[str | None] = mapped_column(String(100))  # free text: the person who made the report (reply 48)  # document_id of the post request (idempotent retry)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # who posted / covered / voided
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["SalesImportLine"]] = relationship(cascade="all, delete-orphan", order_by="SalesImportLine.line_no")
    usage: Mapped[list["SalesImportUsage"]] = relationship(cascade="all, delete-orphan", order_by="SalesImportUsage.id")


class SalesImportLine(Base):
    """One POS item of the report; rows with the same code are summed (returns included)."""

    __tablename__ = "sales_import_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_imports.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    pos_code: Mapped[str] = mapped_column(String(32))
    pos_name: Mapped[str] = mapped_column(String(128))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))


class SalesImportUsage(Base):
    """Snapshot of the usage at posting/covering: which POS item consumed how much of which product."""

    __tablename__ = "sales_import_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_imports.id", ondelete="CASCADE"))
    pos_code: Mapped[str] = mapped_column(String(32))
    pos_name: Mapped[str] = mapped_column(String(128))
    sold_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    per_unit_base: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    qty_base: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    # Not written off: this completed inventory counted the product after the sales (reply 39, P2).
    covered_inventory_id: Mapped[int | None] = mapped_column(ForeignKey("inventories.id"))
    covered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Cost per base unit the product was written off at (the current price, or the one typed in the report).
    unit_cost_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
