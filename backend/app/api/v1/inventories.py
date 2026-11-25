"""Inventory counts API (requirements 2.5)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.api.deps import DbSession, require
from app.api.errors import integrity_to_http
from app.api.v1.settings import load_settings
from app.core.permissions import Perm, has_perm
from app.models import (
    BaseUnit,
    Category,
    Inventory,
    InventoryLine,
    InventoryStatus,
    Location,
    Product,
    StockBalance,
    Unit,
    User,
)
from app.services import inventory as svc
from app.services.posting import current_cost

router = APIRouter(prefix="/inventories", tags=["inventory"])
Counter = Annotated[User, Depends(require(Perm.inventory_count))]
Reviewer = Annotated[User, Depends(require(Perm.inventory_review))]
Viewer = Annotated[User, Depends(require(Perm.view))]


# ------------------------------------------------------------------ schemas
class StartIn(BaseModel):
    location_id: int
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class Part(BaseModel):
    qty: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]
    qty_unit: Unit | None = None


class CountIn(BaseModel):
    # e.g. [{qty: 2, qty_unit: bottle}, {qty: 350, qty_unit: ml}] = two full bottles and an open one
    parts: list[Part] = Field(min_length=1, max_length=4)
    counted_at: datetime | None = None  # device time of pressing "counted"
    sent_at: datetime | None = None  # device time of sending; corrects the device clock error
    version: int | None = None  # the line version the client saw; None = overwrite


class ClearIn(BaseModel):
    version: int | None = None


class CompleteIn(BaseModel):
    zero_uncounted: bool = False


class LineOut(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    category_code: str | None
    category_name: str
    unit: Unit
    base_unit: BaseUnit
    unit_size: Decimal
    product_active: bool
    counted_base: Decimal | None
    counted_at: datetime | None
    counted_by_name: str | None
    version: int
    # Hidden (null) for staff when settings.blind_count is on.
    expected_at_start_base: Decimal | None
    expected_base: Decimal | None  # in progress: as of the count (display); completed: the value used
    diff_base: Decimal | None
    unit_cost_base: Decimal | None
    diff_cost: Decimal | None  # unrounded


class InventoryOut(BaseModel):
    id: int
    location_id: int
    location_name: str
    status: InventoryStatus
    comment: str
    started_at: datetime
    started_by_name: str
    closed_at: datetime | None  # completion or cancellation time, see status
    closed_by_name: str | None
    adjustment_document_id: str | None
    line_count: int
    counted_count: int
    blind: bool
    surplus_cost: Decimal | None
    shortage_cost: Decimal | None
    net_cost: Decimal | None


class InventoryDetail(InventoryOut):
    lines: list[LineOut]


# ------------------------------------------------------------------ helpers
def _blind(db: Session, user: User) -> bool:
    return load_settings(db).blind_count and not has_perm(user.role, Perm.inventory_review)


def _name(u: type[User]):
    return func.coalesce(func.nullif(u.full_name, ""), u.username)


def _detail(db: Session, user: User, inv: Inventory, with_lines: bool = True) -> InventoryDetail:
    blind = _blind(db, user)
    starter, closer, counter = aliased(User), aliased(User), aliased(User)
    loc_name, start_name, close_name = db.execute(
        select(Location.name, _name(starter), _name(closer))
        .select_from(Inventory)
        .join(Location, Location.id == Inventory.location_id)
        .join(starter, starter.id == Inventory.started_by)
        .outerjoin(closer, closer.id == Inventory.completed_by)
        .where(Inventory.id == inv.id)
    ).one()

    rows = db.execute(
        select(InventoryLine, Product, Category, _name(counter), StockBalance.qty_base)
        .join(Product, Product.id == InventoryLine.product_id)
        .join(Category, Category.id == Product.category_id)
        .outerjoin(counter, counter.id == InventoryLine.counted_by)
        .outerjoin(StockBalance, and_(StockBalance.product_id == Product.id, StockBalance.location_id == inv.location_id))
        .where(InventoryLine.inventory_id == inv.id)
        .order_by(func.lower(Product.name))
    ).all()

    lines: list[LineOut] = []
    surplus = shortage = Decimal(0)
    for line, p, c, counter_name, balance in rows:
        if inv.status == InventoryStatus.completed:
            expected, cost = line.expected_at_count_base, line.unit_cost_base
        else:
            # display: the expected value saved when counted, or the live balance for lines not counted yet
            expected = line.expected_at_count_base if line.counted_base is not None else Decimal(balance or 0)
            cost = current_cost(p)
        diff = (line.counted_base - expected) if line.counted_base is not None and expected is not None else None
        diff_cost = diff * cost if diff is not None and cost is not None else None
        if diff_cost is not None:
            if diff_cost > 0:
                surplus += diff_cost
            else:
                shortage += diff_cost
        lines.append(
            LineOut(
                product_id=p.id, product_name=p.name, product_sku=p.sku, category_code=c.code, category_name=c.name,
                unit=p.unit, base_unit=p.base_unit, unit_size=p.unit_size, product_active=p.is_active,
                counted_base=line.counted_base, counted_at=line.counted_at, counted_by_name=counter_name, version=line.version,
                expected_at_start_base=None if blind else line.expected_at_start_base,
                expected_base=None if blind else expected,
                diff_base=None if blind else diff,
                unit_cost_base=None if blind else cost,
                diff_cost=None if blind else diff_cost,
            )
        )
    return InventoryDetail(
        id=inv.id, location_id=inv.location_id, location_name=loc_name, status=inv.status, comment=inv.comment,
        started_at=inv.started_at, started_by_name=start_name, closed_at=inv.completed_at, closed_by_name=close_name,
        adjustment_document_id=str(inv.adjustment_document_id) if inv.adjustment_document_id else None,
        line_count=len(lines), counted_count=sum(1 for x in lines if x.counted_base is not None), blind=blind,
        surplus_cost=None if blind else surplus, shortage_cost=None if blind else shortage,
        net_cost=None if blind else surplus + shortage,
        lines=lines if with_lines else [],
    )


def _get(db: Session, inventory_id: int) -> Inventory:
    inv = db.get(Inventory, inventory_id, populate_existing=True)
    if inv is None:
        raise HTTPException(404, "Inventory not found")
    return inv


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise integrity_to_http(e) from None


def _run(db: Session, fn):
    try:
        result = fn()
        _commit(db)
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as e:  # e.g. a second inventory in progress for the same location (flush in the service)
        db.rollback()
        raise integrity_to_http(e) from None


# ---------------------------------------------------------------- endpoints
@router.get("", response_model=list[InventoryOut])
def list_inventories(
    user: Viewer,
    db: DbSession,
    location_id: int | None = None,
    status: InventoryStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    exclude_cancelled: bool = False,
) -> list[InventoryOut]:
    stmt = select(Inventory)
    if location_id is not None:
        stmt = stmt.where(Inventory.location_id == location_id)
    if status is not None:
        stmt = stmt.where(Inventory.status == status)
    if exclude_cancelled:
        stmt = stmt.where(Inventory.status != InventoryStatus.cancelled)
    stmt = stmt.order_by(case((Inventory.status == InventoryStatus.in_progress, 0), else_=1), Inventory.started_at.desc()).limit(limit)
    return [InventoryOut(**_detail(db, user, inv, with_lines=False).model_dump(exclude={"lines"})) for inv in db.scalars(stmt)]


@router.post("", response_model=InventoryDetail, status_code=201)
def start_inventory(body: StartIn, user: Counter, db: DbSession) -> InventoryDetail:
    inv = _run(db, lambda: svc.start(db, user, body.location_id, body.comment))
    return _detail(db, user, _get(db, inv.id))


@router.get("/{inventory_id}", response_model=InventoryDetail)
def get_inventory(inventory_id: int, user: Viewer, db: DbSession) -> InventoryDetail:
    return _detail(db, user, _get(db, inventory_id))


@router.put("/{inventory_id}/lines/{product_id}", response_model=LineOut)
def count_line(inventory_id: int, product_id: int, body: CountIn, user: Counter, db: DbSession) -> LineOut:
    _run(db, lambda: svc.count_line(db, user, inventory_id, product_id, [(x.qty, x.qty_unit) for x in body.parts], body.counted_at, body.sent_at, body.version))
    detail = _detail(db, user, _get(db, inventory_id))
    return next(x for x in detail.lines if x.product_id == product_id)


@router.delete("/{inventory_id}/lines/{product_id}/count", response_model=LineOut)
def clear_count(inventory_id: int, product_id: int, user: Counter, db: DbSession, version: int | None = None) -> LineOut:
    _run(db, lambda: svc.clear_count(db, inventory_id, product_id, version))
    detail = _detail(db, user, _get(db, inventory_id))
    return next(x for x in detail.lines if x.product_id == product_id)


@router.post("/{inventory_id}/complete", response_model=InventoryDetail)
def complete_inventory(inventory_id: int, body: CompleteIn, user: Reviewer, db: DbSession) -> InventoryDetail:
    _run(db, lambda: svc.complete(db, user, inventory_id, body.zero_uncounted))
    return _detail(db, user, _get(db, inventory_id))


@router.post("/{inventory_id}/cancel", response_model=InventoryDetail)
def cancel_inventory(inventory_id: int, user: Reviewer, db: DbSession) -> InventoryDetail:
    _run(db, lambda: svc.cancel(db, user, inventory_id))
    return _detail(db, user, _get(db, inventory_id))
