from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.catalog import BaseUnit, Unit

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
ProductName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Sku = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Barcode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[0-9A-Za-z\-]+$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Qty = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]
Weight = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=1)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ categories
class CategoryOut(ORM):
    id: int
    code: str | None
    name: str
    is_active: bool


class CategoryCreate(BaseModel):
    name: Name


class CategoryUpdate(BaseModel):
    name: Name | None = None
    is_active: bool | None = None


# ------------------------------------------------------------------- locations
class LocationOut(ORM):
    id: int
    name: str
    description: str
    is_active: bool
    product_count: int = 0  # products with a non-zero balance here
    has_active_inventory: bool = False


class LocationCreate(BaseModel):
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] = ""


class LocationUpdate(BaseModel):
    name: Name | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    is_active: bool | None = None


# -------------------------------------------------------------------- products
class LocationBalance(BaseModel):
    location_id: int
    location_name: str
    location_active: bool
    qty_base: Decimal


class ProductOut(ORM):
    id: int
    name: str
    sku: str
    category_id: int
    category_code: str | None
    category_name: str
    unit: Unit
    base_unit: BaseUnit
    unit_size: Decimal
    purchase_price: Decimal
    price_updated_at: datetime | None
    min_stock_base: Decimal
    barcode: str | None
    full_weight_g: Decimal | None
    empty_weight_g: Decimal | None
    is_active: bool
    total_qty_base: Decimal = Decimal("0")
    stock_value: Decimal = Decimal("0")  # current-price valuation (architecture section 4)
    is_low_stock: bool = False
    units_locked: bool = False  # unit/base_unit/unit_size are frozen once the product has movements
    # Usage over all places in the requested period (`used_days`); None when not requested (app/services/usage.py)
    used_base: Decimal | None = None
    count_loss_base: Decimal | None = None


class ProductDetail(ProductOut):
    balances: list[LocationBalance] = []


class HistoryPoint(BaseModel):
    day: date  # business day
    balance: Decimal  # over all places at the end of the day, base units
    qty_in: Decimal  # came in that day (receipts, count surpluses, ...); transfers between places are neither
    qty_out: Decimal  # went out that day (write-offs, POS sales, count shortages, ...)


class HistoryPlace(BaseModel):
    location_id: int
    location_name: str
    balances: list[Decimal]  # one per point


class ProductHistory(BaseModel):
    product_id: int
    min_stock_base: Decimal
    days: int
    points: list[HistoryPoint]
    places: list[HistoryPlace]


class ProductCreate(BaseModel):
    name: ProductName
    sku: Sku
    category_id: int
    unit: Unit
    unit_size: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)] | None = None
    purchase_price: Money = Decimal("0")
    price_currency: Literal["KRW", "USD"] = "KRW"  # USD: converted to won at the current rate (reply 34)
    min_stock_base: Qty = Decimal("0")
    barcode: Barcode | None = None
    full_weight_g: Weight | None = None
    empty_weight_g: Weight | None = None


class ProductUpdate(BaseModel):
    name: ProductName | None = None
    sku: Sku | None = None
    category_id: int | None = None
    unit: Unit | None = None
    unit_size: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)] | None = None
    purchase_price: Money | None = None
    price_currency: Literal["KRW", "USD"] = "KRW"
    min_stock_base: Qty | None = None
    barcode: Barcode | None = None
    full_weight_g: Weight | None = None
    empty_weight_g: Weight | None = None
    is_active: bool | None = None


class ProductPage(BaseModel):
    items: list[ProductOut]
    total: int
