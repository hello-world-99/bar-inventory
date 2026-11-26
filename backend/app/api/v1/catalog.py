"""Categories, storage locations and products (requirements 2.2, 2.3)."""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, require
from app.api.errors import integrity_to_http
from app.core.permissions import Perm
from app.core.units import BASE_OF, UnitError, resolve_unit_size
from app.services import history as history_service
from app.services import usage as usage_service
from app.services.posting import to_won, usd_rate
from app.models import (
    Category,
    Inventory,
    InventoryLine,
    InventoryStatus,
    Location,
    Product,
    StockBalance,
    StockDocumentLine,
    StockMovement,
    User,
)
from app.schemas_catalog import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    LocationBalance,
    LocationCreate,
    LocationOut,
    LocationUpdate,
    ProductCreate,
    ProductHistory,
    ProductDetail,
    ProductOut,
    ProductPage,
    ProductUpdate,
)

router = APIRouter(tags=["catalog"])
Manager = Annotated[User, Depends(require(Perm.manage_catalog))]
Viewer = Annotated[User, Depends(require(Perm.view))]
ActiveFilter = Literal["active", "inactive", "all"]


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise integrity_to_http(e) from None


def _active_clause(col, active: ActiveFilter):
    return {"active": col.is_(True), "inactive": col.is_(False), "all": True}[active]


# ====================================================================== categories
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(_: Viewer, db: DbSession, active: ActiveFilter = "active") -> list[Category]:
    q = select(Category).where(_active_clause(Category.is_active, active)).order_by(Category.id)
    return list(db.scalars(q))


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryCreate, _: Manager, db: DbSession) -> Category:
    c = Category(name=body.name, is_active=True)
    db.add(c)
    _commit(db)
    return c


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, body: CategoryUpdate, _: Manager, db: DbSession) -> Category:
    c = db.get(Category, category_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    if body.name is not None and body.name != c.name:
        if c.code is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Built-in categories cannot be renamed (they are translated)")
        c.name = body.name
    if body.is_active is not None:
        c.is_active = body.is_active
    _commit(db)
    return c


# ======================================================================= locations
def _location_out(db: Session, locs: list[Location]) -> list[LocationOut]:
    if not locs:
        return []
    ids = [loc.id for loc in locs]
    counts = dict(
        db.execute(
            select(StockBalance.location_id, func.count())
            .where(StockBalance.location_id.in_(ids), StockBalance.qty_base != 0)
            .group_by(StockBalance.location_id)
        ).all()
    )
    active_inv = set(
        db.scalars(
            select(Inventory.location_id).where(
                Inventory.location_id.in_(ids), Inventory.status == InventoryStatus.in_progress
            )
        )
    )
    out = []
    for loc in locs:
        o = LocationOut.model_validate(loc)
        o.product_count = counts.get(loc.id, 0)
        o.has_active_inventory = loc.id in active_inv
        out.append(o)
    return out


@router.get("/locations", response_model=list[LocationOut])
def list_locations(_: Viewer, db: DbSession, active: ActiveFilter = "active") -> list[LocationOut]:
    q = select(Location).where(_active_clause(Location.is_active, active)).order_by(func.lower(Location.name))
    return _location_out(db, list(db.scalars(q)))


@router.post("/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
def create_location(body: LocationCreate, _: Manager, db: DbSession) -> LocationOut:
    loc = Location(name=body.name, description=body.description, is_active=True)
    db.add(loc)
    _commit(db)
    return _location_out(db, [loc])[0]


@router.patch("/locations/{location_id}", response_model=LocationOut)
def update_location(location_id: int, body: LocationUpdate, _: Manager, db: DbSession) -> LocationOut:
    loc = db.get(Location, location_id, with_for_update=True)
    if loc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    if body.is_active is False and loc.is_active:
        busy = db.scalar(
            select(exists().where(Inventory.location_id == loc.id, Inventory.status == InventoryStatus.in_progress))
        )
        if busy:
            raise HTTPException(status.HTTP_409_CONFLICT, "Finish or cancel the inventory in progress first")
    for field in ("name", "description", "is_active"):
        value = getattr(body, field)
        if value is not None:
            setattr(loc, field, value)
    _commit(db)
    return _location_out(db, [loc])[0]


# ======================================================================== products
_totals = (
    select(StockBalance.product_id, func.sum(StockBalance.qty_base).label("total"))
    .group_by(StockBalance.product_id)
    .subquery()
)
_total = func.coalesce(_totals.c.total, 0)
_value = _total * Product.purchase_price / Product.unit_size
_low = and_(Product.min_stock_base > 0, _total <= Product.min_stock_base)
# Units are frozen once any quantity in base units refers to the product: posted movements,
# draft/posted document lines or inventory lines (changing bottle -> kg would turn stored ml into g).
_locked = or_(
    exists().where(StockMovement.product_id == Product.id),
    exists().where(StockDocumentLine.product_id == Product.id),
    exists().where(InventoryLine.product_id == Product.id),
)

SORTS = {
    "name": func.lower(Product.name),
    "sku": func.lower(Product.sku),
    "category": Category.name,
    "total_qty": _total,
    "stock_value": _value,
    "price": Product.purchase_price,
}


def _product_query() -> Select:
    return (
        select(
            Product,
            _total.label("total_qty_base"),
            _value.label("stock_value"),
            case((_low, True), else_=False).label("is_low_stock"),
            _locked.label("units_locked"),
        )
        .join(Category, Product.category_id == Category.id)
        .outerjoin(_totals, _totals.c.product_id == Product.id)
    )


def _to_out(row, cls=ProductOut):
    p: Product = row[0]
    return cls(
        **{k: getattr(p, k) for k in ProductOut.model_fields if hasattr(p, k) and k not in {"category_code", "category_name"}},
        category_code=p.category.code,
        category_name=p.category.name,
        total_qty_base=Decimal(row.total_qty_base).quantize(Decimal("0.001")),
        # Unrounded (6 dp); money is rounded only for display, per settings.currency_decimals.
        stock_value=Decimal(row.stock_value).quantize(Decimal("0.000001")),
        is_low_stock=row.is_low_stock,
        units_locked=row.units_locked,
    )


@router.get("/products", response_model=ProductPage)
def list_products(
    _: Viewer,
    db: DbSession,
    q: Annotated[str | None, Query(max_length=128)] = None,
    category_id: int | None = None,
    location_id: Annotated[int | None, Query(description="only products with a balance row at this location")] = None,
    active: ActiveFilter = "active",
    low_stock: bool = False,
    sort: Literal["name", "sku", "category", "total_qty", "stock_value", "price"] = "name",
    order: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    used_days: Annotated[int | None, Query(description="usage over the last 1, 7 or 30 business days")] = None,
) -> ProductPage:
    stmt = _product_query().where(_active_clause(Product.is_active, active))
    if q:
        term = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                func.lower(Product.name).like(like, escape="\\"),
                func.lower(Product.sku).like(like, escape="\\"),
                Product.barcode == q.strip(),
            )
        )
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if location_id is not None:
        stmt = stmt.where(
            exists().where(StockBalance.product_id == Product.id, StockBalance.location_id == location_id)
        )
    if low_stock:
        stmt = stmt.where(_low)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    key = SORTS[sort]
    stmt = stmt.order_by(key.desc() if order == "desc" else key.asc(), Product.id).limit(limit).offset(offset)
    usage_service.check_period(used_days)
    items = [_to_out(r) for r in db.execute(stmt)]
    if used_days:
        used = usage_service.usage(db, used_days, by_location=False)
        for it in items:
            it.used_base, it.count_loss_base = used.get((it.id,), (Decimal(0), Decimal(0)))
    return ProductPage(items=items, total=total)


def _get_product_row(db: Session, product_id: int):
    row = db.execute(_product_query().where(Product.id == product_id)).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return row


@router.get("/products/{product_id}/history", response_model=ProductHistory)
def product_history(product_id: int, _: Viewer, db: DbSession, days: int = 30) -> ProductHistory:
    """Stock at the end of each business day (the chart on the product card, reply 98)."""
    history_service.check_period(days)
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return ProductHistory(product_id=product.id, min_stock_base=product.min_stock_base, **history_service.history(db, product.id, days))


@router.get("/products/{product_id}", response_model=ProductDetail)
def get_product(product_id: int, _: Viewer, db: DbSession) -> ProductDetail:
    out = _to_out(_get_product_row(db, product_id), ProductDetail)
    rows = db.execute(
        select(Location.id, Location.name, Location.is_active, StockBalance.qty_base)
        .join(StockBalance, StockBalance.location_id == Location.id)
        .where(StockBalance.product_id == product_id)
        .order_by(func.lower(Location.name))
    )
    out.balances = [
        LocationBalance(location_id=i, location_name=n, location_active=a, qty_base=qty) for i, n, a, qty in rows
    ]
    return out


def _check_category(db: Session, category_id: int) -> None:
    c = db.get(Category, category_id)
    if c is None or not c.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Category not found or inactive")


def _check_weights(full, empty) -> None:
    if full is not None and empty is not None and full <= empty:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Full bottle weight must exceed empty weight")


@router.post("/products", response_model=ProductDetail, status_code=status.HTTP_201_CREATED)
def create_product(body: ProductCreate, user: Manager, db: DbSession) -> ProductDetail:
    _check_category(db, body.category_id)
    _check_weights(body.full_weight_g, body.empty_weight_g)
    try:
        size = resolve_unit_size(body.unit, body.unit_size)
    except UnitError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    price = to_won(body.purchase_price, usd_rate(db) if body.price_currency == "USD" else None)
    p = Product(
        name=body.name,
        sku=body.sku,
        category_id=body.category_id,
        unit=body.unit,
        base_unit=BASE_OF[body.unit],
        unit_size=size,
        purchase_price=price,
        price_updated_at=func.now() if price else None,
        min_stock_base=body.min_stock_base,
        barcode=body.barcode,
        full_weight_g=body.full_weight_g,
        empty_weight_g=body.empty_weight_g,
        is_active=True,
    )
    db.add(p)
    _commit(db)
    return get_product(p.id, user, db)


@router.patch("/products/{product_id}", response_model=ProductDetail)
def update_product(product_id: int, body: ProductUpdate, user: Manager, db: DbSession) -> ProductDetail:
    p = db.get(Product, product_id, with_for_update=True)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    sent = body.model_fields_set

    if "unit" in sent or "unit_size" in sent:
        new_unit = body.unit or p.unit
        if body.unit is None and "unit" in sent:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unit cannot be null")
        size_in = body.unit_size if "unit_size" in sent else (p.unit_size if new_unit == p.unit else None)
        try:
            new_size = resolve_unit_size(new_unit, size_in)
        except UnitError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
        if new_unit != p.unit or new_size != p.unit_size:
            if db.scalar(select(_locked).where(Product.id == p.id)):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Units cannot change once the product is used in documents or counts; "
                    "create a new product and deactivate this one",
                )
            p.unit, p.base_unit, p.unit_size = new_unit, BASE_OF[new_unit], new_size

    for field in ("name", "sku", "min_stock_base"):
        if field in sent:
            value = getattr(body, field)
            if value is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} cannot be null")
            setattr(p, field, value)
    if "category_id" in sent:
        if body.category_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "category_id cannot be null")
        if body.category_id != p.category_id:
            _check_category(db, body.category_id)
        p.category_id = body.category_id
    price = None
    if "purchase_price" in sent and body.purchase_price is not None:
        price = to_won(body.purchase_price, usd_rate(db) if body.price_currency == "USD" else None)
    if price is not None and price != p.purchase_price:
        p.purchase_price = price
        p.price_updated_at = func.now()  # a manual price wins over receipts dated earlier
    for field in ("barcode", "full_weight_g", "empty_weight_g"):  # nullable: explicit null clears
        if field in sent:
            setattr(p, field, getattr(body, field))
    if "is_active" in sent and body.is_active is not None:
        p.is_active = body.is_active
    _check_weights(p.full_weight_g, p.empty_weight_g)
    _commit(db)
    db.expire_all()
    return get_product(p.id, user, db)
