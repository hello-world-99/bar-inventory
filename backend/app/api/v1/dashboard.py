"""Dashboard (requirements 2.1): headline numbers, low stock, recent receipts/write-offs, recent counts."""

from decimal import Decimal

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, select

from app.api.deps import DbSession, require
from app.api.v1.documents import list_documents
from app.api.v1.inventories import InventoryOut, list_inventories
from app.core.permissions import Perm
from app.models import Location, Product, StockBalance, Unit, User
from app.schemas_docs import DocSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class LowStockItem(BaseModel):
    product_id: int
    name: str
    sku: str
    unit: Unit
    base_unit: str
    unit_size: Decimal
    total_qty_base: Decimal
    min_stock_base: Decimal


class LocationValue(BaseModel):
    location_id: int
    name: str
    value: Decimal
    product_count: int


class Dashboard(BaseModel):
    product_count: int  # active products
    location_count: int  # active locations
    stock_value: Decimal  # current-price valuation, unrounded
    in_stock_count: int  # active products with total stock > 0
    low_stock_count: int
    negative_count: int  # (product, location) pairs below zero - something to check
    by_location: list[LocationValue]
    low_stock: list[LowStockItem]
    recent_receipts: list[DocSummary]
    recent_write_offs: list[DocSummary]
    recent_inventories: list[InventoryOut]


@router.get("", response_model=Dashboard)
def dashboard(user: Annotated[User, Depends(require(Perm.view))], db: DbSession) -> Dashboard:

    value = StockBalance.qty_base * Product.purchase_price / Product.unit_size
    totals = (
        select(StockBalance.product_id, func.sum(StockBalance.qty_base).label("total"))
        .group_by(StockBalance.product_id)
        .subquery()
    )
    total = func.coalesce(totals.c.total, 0)

    product_count = db.scalar(select(func.count()).select_from(Product).where(Product.is_active)) or 0
    location_count = db.scalar(select(func.count()).select_from(Location).where(Location.is_active)) or 0
    stock_value = db.scalar(select(func.coalesce(func.sum(value), 0)).select_from(StockBalance).join(Product, Product.id == StockBalance.product_id)) or 0
    in_stock = db.scalar(
        select(func.count()).select_from(Product).outerjoin(totals, totals.c.product_id == Product.id).where(Product.is_active, total > 0)
    ) or 0
    low_cond = and_(Product.is_active, Product.min_stock_base > 0, total <= Product.min_stock_base)
    low_rows = db.execute(
        select(Product, total)
        .outerjoin(totals, totals.c.product_id == Product.id)
        .where(low_cond)
        .order_by((total / Product.min_stock_base).asc(), func.lower(Product.name))
    ).all()
    negative = db.scalar(select(func.count()).select_from(StockBalance).where(StockBalance.qty_base < 0)) or 0
    by_loc = db.execute(
        select(Location.id, Location.name, func.coalesce(func.sum(value), 0), func.count().filter(StockBalance.qty_base != 0))
        .join(StockBalance, StockBalance.location_id == Location.id)
        .join(Product, Product.id == StockBalance.product_id)
        .where(Location.is_active)
        .group_by(Location.id, Location.name)
        .order_by(func.lower(Location.name))
    ).all()

    return Dashboard(
        product_count=product_count,
        location_count=location_count,
        stock_value=Decimal(stock_value),
        in_stock_count=in_stock,
        low_stock_count=len(low_rows),
        negative_count=negative,
        by_location=[LocationValue(location_id=i, name=n, value=Decimal(v), product_count=c) for i, n, v, c in by_loc],
        low_stock=[
            LowStockItem(product_id=p.id, name=p.name, sku=p.sku, unit=p.unit, base_unit=p.base_unit.value, unit_size=p.unit_size,
                         total_qty_base=Decimal(t), min_stock_base=p.min_stock_base)
            for p, t in low_rows[:10]
        ],
        recent_receipts=list_documents(user, db, type=["receipt"], limit=5).items,
        recent_write_offs=list_documents(user, db, type=["write_off"], limit=5).items,
        recent_inventories=[i for i in list_inventories(user, db, limit=10) if i.status != "cancelled"][:5],
    )
