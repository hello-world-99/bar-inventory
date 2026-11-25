import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models import BaseUnit, SalesImportStatus, Unit
from app.schemas_docs import QtyIn


class UsagePart(BaseModel):
    pos_code: str
    pos_name: str
    sold_qty: Decimal
    per_unit_base: Decimal
    qty_base: Decimal


class UsageItem(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    unit: Unit
    base_unit: BaseUnit
    unit_size: Decimal
    is_active: bool
    qty_base: Decimal
    unit_cost_base: Decimal
    amount: Decimal
    balance_base: Decimal | None  # at the chosen location (drafts only)
    min_stock_base: Decimal
    # Not written off: this completed inventory counted it after the sales (drafts: would be skipped).
    covered_inventory_id: int | None = None
    covered_at: datetime | None = None
    written_off_base: Decimal | None = None  # what the write-off holds for this product (written-off reports)
    parts: list[UsagePart]


class PosLineOut(BaseModel):
    pos_item_id: int | None
    code: str
    name: str
    qty: Decimal
    revenue: Decimal | None


class SalesImportSummary(BaseModel):
    id: uuid.UUID
    sales_date: date
    status: SalesImportStatus
    file_name: str
    total_qty: Decimal
    total_revenue: Decimal | None
    location_id: int | None
    location_name: str | None
    write_off_id: uuid.UUID | None
    uploaded_by_name: str
    uploaded_at: datetime
    closed_by_name: str | None
    closed_at: datetime | None
    warning_count: int
    prepared_by: str | None = None


class SalesImportOut(SalesImportSummary):
    file_sha256: str
    covered_inventory_id: int | None
    warnings: list[dict[str, Any]]
    items: list[UsageItem]
    unmapped: list[PosLineOut]  # kitchen status unknown: no norm and not marked "not kitchen"
    not_kitchen: list[PosLineOut]
    line_count: int


class SalesImportList(BaseModel):
    default_sales_date: date  # the previous business day
    items: list[SalesImportSummary]


class PostLineIn(BaseModel):
    """A product's usage as corrected in the report before writing off (owner, 2026-11-25)."""

    product_id: int
    qty_base: Decimal = Field(ge=0, max_digits=14, decimal_places=3)  # 0: do not write this product off
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)  # per product unit


class PostIn(BaseModel):
    document_id: uuid.UUID  # client-generated id of the write-off; a retry returns the same report
    location_id: int
    allow_negative: bool = False
    acknowledge_unmapped: bool = False
    lines: list[PostLineIn] = Field(default_factory=list, max_length=500)
    price_currency: Literal["KRW", "USD"] = "KRW"  # of lines[].unit_price
    prepared_by: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None  # who made the report; None keeps it


class CorrectIn(BaseModel):
    """Edit a written-off report: its write-off is reversed (reversal_id) and a new one posted (document_id)."""

    document_id: uuid.UUID
    reversal_id: uuid.UUID
    lines: list[PostLineIn] = Field(default_factory=list, max_length=500)
    price_currency: Literal["KRW", "USD"] = "KRW"
    allow_negative: bool = False
    prepared_by: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None


class PreparedByIn(BaseModel):
    prepared_by: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None


class VoidIn(BaseModel):
    reversal_id: uuid.UUID  # client-generated id of the reversal document


class ComponentOut(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    unit: Unit
    base_unit: BaseUnit
    unit_size: Decimal
    is_active: bool
    qty_base: Decimal


class PosItemOut(BaseModel):
    id: int
    code: str
    name: str
    not_kitchen: bool
    components: list[ComponentOut]
    updated_at: datetime


class PosItemIn(BaseModel):
    not_kitchen: bool = False
    components: list[QtyIn] = Field(default_factory=list, max_length=20)


class NotKitchenIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)


class PendingDays(BaseModel):
    location_id: int
    last_imported: date | None
    days: list[date]  # business days after the last imported one, up to today, without a posted/covered report
    more: int  # days beyond the list limit
