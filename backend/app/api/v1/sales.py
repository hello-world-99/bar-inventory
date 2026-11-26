"""POS sales imports and kitchen norms (agent-room replies 30-32).

The upload is the raw .xlsx body (no multipart: no python-multipart dependency, reply 32 P2); id, date and file
name travel in the query string.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from app.api.deps import DbSession, require
from app.api.errors import constraint_name
from app.core.permissions import Perm
from app.core.units import UnitError, to_base
from app.models import (
    Location,
    PosItem,
    PosItemComponent,
    Product,
    SalesImport,
    SalesImportStatus,
    StockBalance,
    User,
)
from app.schemas_sales import (
    ComponentOut,
    CorrectIn,
    NotKitchenIn,
    PendingDays,
    PosItemIn,
    PosItemOut,
    PosLineOut,
    PreparedByIn,
    PostIn,
    SalesImportList,
    SalesImportOut,
    SalesImportSummary,
    UsageItem,
    UsagePart,
    VoidIn,
)
from app.services import sales
from app.services.pos_xlsx import MAX_FILE_BYTES, ParseError
from app.services.posting import current_cost, error

router = APIRouter(tags=["sales"])
Viewer = Annotated[User, Depends(require(Perm.view))]
Poster = Annotated[User, Depends(require(Perm.post_write_off))]
Admin = Annotated[User, Depends(require(Perm.reverse_document))]
Manager = Annotated[User, Depends(require(Perm.manage_catalog))]


# ------------------------------------------------------------------ helpers
async def xlsx_body(request: Request) -> bytes:
    """The request body, cut at the size limit (Content-Length is checked first, then the bytes actually read)."""
    too_large = HTTPException(422, {"code": "file_too_large", "message": f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"})
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise too_large
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_FILE_BYTES:
            raise too_large
    if not data:
        raise HTTPException(422, {"code": "bad_file", "message": "The file is empty"})
    return bytes(data)


def _name(u: type[User]):
    return func.coalesce(func.nullif(u.full_name, ""), u.username)


def _summaries(db: Session, *where, limit: int = 200) -> list[SalesImportSummary]:
    up, cl = aliased(User), aliased(User)
    rows = db.execute(
        select(SalesImport, _name(up), _name(cl), Location.name)
        .join(up, up.id == SalesImport.uploaded_by)
        .outerjoin(cl, cl.id == SalesImport.closed_by)
        .outerjoin(Location, Location.id == SalesImport.location_id)
        .where(*where)
        .order_by(SalesImport.sales_date.desc(), SalesImport.uploaded_at.desc())
        .limit(limit)
    ).all()
    return [
        SalesImportSummary(
            id=i.id, sales_date=i.sales_date, status=i.status, file_name=i.file_name, total_qty=i.total_qty,
            total_revenue=i.total_revenue, location_id=i.location_id, location_name=loc, write_off_id=i.write_off_id,
            uploaded_by_name=up_name, uploaded_at=i.uploaded_at, closed_by_name=cl_name, closed_at=i.closed_at,
            warning_count=len(i.warnings or []), prepared_by=i.prepared_by,
        )
        for i, up_name, cl_name, loc in rows
    ]


def _line(line, items: dict[str, int]) -> PosLineOut:
    return PosLineOut(pos_item_id=items.get(line.pos_code), code=line.pos_code, name=line.pos_name, qty=line.qty, revenue=line.revenue)


def _report(db: Session, imp: SalesImport, location_id: int | None = None) -> SalesImportOut:
    db.refresh(imp)
    usage = sales.compute_usage(db, imp)
    by_product: dict[int, list[UsagePart]] = {}
    frozen_cover = {p.product_id: (p.covered_inventory_id, p.covered_at) for p in usage.parts if p.covered_inventory_id}
    for p in usage.parts:
        by_product.setdefault(p.product_id, []).append(
            UsagePart(pos_code=p.pos_code, pos_name=p.pos_name, sold_qty=p.sold_qty, per_unit_base=p.per_unit_base, qty_base=p.qty_base)
        )
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(by_product)))}
    loc = location_id if imp.status == SalesImportStatus.draft else None
    balances = {}
    totals: dict[int, Decimal] = {}
    covered: dict[int, tuple[int, datetime]] = {}
    if loc is not None:  # preview of what posting at this location would do
        covered = sales.covered_pairs(db, sales.day_start(db, imp.sales_date), loc, by_product)
        balances = dict(db.execute(
            select(StockBalance.product_id, StockBalance.qty_base).where(StockBalance.location_id == loc, StockBalance.product_id.in_(by_product))
        ).all())
        totals = dict(db.execute(
            select(StockBalance.product_id, func.sum(StockBalance.qty_base)).where(StockBalance.product_id.in_(by_product))
            .group_by(StockBalance.product_id)
        ).all())
    written = sales._written_off(db, imp) if imp.status == SalesImportStatus.posted else {}
    items = []
    for pid, parts in by_product.items():
        p = products[pid]
        qty = sum((x.qty_base for x in parts), Decimal(0))
        if qty <= 0:
            continue
        frozen_cost = next((x.unit_cost_base for x in usage.parts if x.product_id == pid and x.unit_cost_base is not None), None)
        cost = frozen_cost if frozen_cost is not None else current_cost(p)
        items.append(UsageItem(
            product_id=p.id, product_name=p.name, product_sku=p.sku, unit=p.unit, base_unit=p.base_unit, unit_size=p.unit_size,
            is_active=p.is_active, qty_base=qty, unit_cost_base=cost, amount=qty * cost,
            balance_base=balances.get(pid, Decimal(0)) if loc is not None else None, parts=parts, min_stock_base=p.min_stock_base,
            total_base=totals.get(pid, Decimal(0)) if loc is not None else None,
            covered_inventory_id=(frozen_cover.get(pid) or covered.get(pid) or (None, None))[0],
            covered_at=(frozen_cover.get(pid) or covered.get(pid) or (None, None))[1],
            written_off_base=written.get(pid, Decimal(0)) if imp.status == SalesImportStatus.posted else None,
        ))
    items.sort(key=lambda x: x.product_name.lower())
    codes = dict(db.execute(select(PosItem.code, PosItem.id).where(PosItem.code.in_([line.pos_code for line in imp.lines]))).all())
    summary = _summaries(db, SalesImport.id == imp.id)[0]
    return SalesImportOut(
        **summary.model_dump(), file_sha256=imp.file_sha256, covered_inventory_id=imp.covered_inventory_id,
        warnings=imp.warnings or [], items=items,
        unmapped=[_line(x, codes) for x in usage.unmapped], not_kitchen=[_line(x, codes) for x in usage.not_kitchen],
        line_count=len(imp.lines),
    )


def _run(db: Session, fn):
    try:
        result = fn()
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except ParseError as e:
        db.rollback()
        raise HTTPException(422, {"code": e.code, "message": e.message, **e.extra}) from None
    except DataError:
        db.rollback()
        raise HTTPException(422, {"code": "invalid_value", "message": "A value is out of the supported range"}) from None


# ------------------------------------------------------------- sales imports
@router.get("/sales-imports", response_model=SalesImportList)
def list_imports(_: Viewer, db: DbSession, date_from: date | None = None, date_to: date | None = None) -> SalesImportList:
    where = []
    if date_from:
        where.append(SalesImport.sales_date >= date_from)
    if date_to:
        where.append(SalesImport.sales_date <= date_to)
    return SalesImportList(default_sales_date=sales.default_sales_date(db), items=_summaries(db, *where))


@router.post("/sales-imports", response_model=SalesImportOut, status_code=201)
def upload_import(
    response: Response,
    user: Poster,
    db: DbSession,
    data: Annotated[bytes, Depends(xlsx_body)],
    id: Annotated[uuid.UUID, Query()],  # noqa: A002
    sales_date: Annotated[date, Query()],
    file_name: Annotated[str, Query(max_length=255)] = "",
    prepared_by: Annotated[str, Query(max_length=100)] = "",
) -> SalesImportOut:
    existed = db.get(SalesImport, id) is not None
    try:
        imp = _run(db, lambda: sales.upload(db, user, id, sales_date, file_name.strip(), data, prepared_by))
    except IntegrityError as e:  # a concurrent upload won the race for the day, the content or the id
        db.rollback()
        name = constraint_name(e)
        if name == "sales_imports_pkey":
            imp = db.get(SalesImport, id)
            if imp is None:
                raise
            return _report(db, imp)
        codes = {"uq_sales_imports_day_active": "already_posted", "uq_sales_imports_content_active": "same_file"}
        if name in codes:
            raise HTTPException(409, {"code": codes[name], "message": "Another upload for this day or of this file just finished; reload"}) from None
        raise
    if existed:
        response.status_code = 200
    return _report(db, imp)


@router.get("/sales-imports/pending-days", response_model=PendingDays)
def get_pending_days(_: Viewer, db: DbSession, location_id: int) -> PendingDays:
    last, days, more = sales.pending_days(db, location_id)
    return PendingDays(location_id=location_id, last_imported=last, days=days, more=more)


@router.get("/sales-imports/{import_id}", response_model=SalesImportOut)
def get_import(import_id: uuid.UUID, _: Viewer, db: DbSession, location_id: int | None = None) -> SalesImportOut:
    imp = db.get(SalesImport, import_id)
    if imp is None:
        raise HTTPException(404, "Sales import not found")
    return _report(db, imp, location_id)


@router.post("/sales-imports/{import_id}/post", response_model=SalesImportOut)
def post_import(import_id: uuid.UUID, body: PostIn, user: Poster, db: DbSession) -> SalesImportOut:
    imp = _run(db, lambda: sales.post(db, user, import_id, body))
    return _report(db, imp)


@router.post("/sales-imports/{import_id}/correct", response_model=SalesImportOut)
def correct_import(import_id: uuid.UUID, body: CorrectIn, user: Admin, db: DbSession) -> SalesImportOut:
    """Edit quantities and prices of a written-off report (reverses its write-off and posts the corrected one)."""
    imp = _run(db, lambda: sales.correct(db, user, import_id, body))
    return _report(db, imp)


@router.patch("/sales-imports/{import_id}", response_model=SalesImportOut)
def sign_import(import_id: uuid.UUID, body: PreparedByIn, user: Poster, db: DbSession) -> SalesImportOut:
    """Who prepared the report (free text); no stock change."""
    imp = _run(db, lambda: sales.set_prepared_by(db, user, import_id, body.prepared_by))
    return _report(db, imp)


@router.post("/sales-imports/{import_id}/void", response_model=SalesImportOut)
def void_import(import_id: uuid.UUID, body: VoidIn, user: Admin, db: DbSession) -> SalesImportOut:
    imp = _run(db, lambda: sales.void(db, user, import_id, body))
    return _report(db, imp)


@router.delete("/sales-imports/{import_id}", status_code=204)
def discard_import(import_id: uuid.UUID, _: Poster, db: DbSession) -> Response:
    _run(db, lambda: sales.discard(db, import_id))
    return Response(status_code=204)


# ------------------------------------------------------------------ norms
def _item_out(db: Session, item: PosItem) -> PosItemOut:
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_([c.product_id for c in item.components])))}
    return PosItemOut(
        id=item.id, code=item.code, name=item.name, not_kitchen=item.not_kitchen, updated_at=item.updated_at,
        components=[
            ComponentOut(
                product_id=c.product_id, product_name=products[c.product_id].name, product_sku=products[c.product_id].sku,
                unit=products[c.product_id].unit, base_unit=products[c.product_id].base_unit,
                unit_size=products[c.product_id].unit_size, is_active=products[c.product_id].is_active, qty_base=c.qty_base,
            )
            for c in item.components
        ],
    )


@router.get("/pos-items", response_model=list[PosItemOut])
def list_pos_items(_: Viewer, db: DbSession) -> list[PosItemOut]:
    items = db.scalars(select(PosItem).options(selectinload(PosItem.components)).order_by(PosItem.not_kitchen, func.lower(PosItem.name)))
    return [_item_out(db, i) for i in items]


@router.post("/pos-items/not-kitchen", response_model=list[PosItemOut])
def mark_not_kitchen(body: NotKitchenIn, _: Manager, db: DbSession) -> list[PosItemOut]:
    """Bulk "not kitchen" for the first import, where every drink shows up without a norm. Items that have a norm
    are left alone."""
    def apply() -> None:
        db.execute(
            update(PosItem)
            .where(PosItem.id.in_(body.ids), ~select(PosItemComponent.pos_item_id).where(PosItemComponent.pos_item_id == PosItem.id).exists())
            .values(not_kitchen=True, updated_at=func.now())
        )

    _run(db, apply)
    items = db.scalars(select(PosItem).where(PosItem.id.in_(body.ids)).options(selectinload(PosItem.components)).order_by(PosItem.id)
                       .execution_options(populate_existing=True))
    return [_item_out(db, i) for i in items]


@router.put("/pos-items/{item_id}", response_model=PosItemOut)
def update_pos_item(item_id: int, body: PosItemIn, _: Manager, db: DbSession) -> PosItemOut:
    def apply() -> PosItem:
        item = db.scalar(select(PosItem).where(PosItem.id == item_id).options(selectinload(PosItem.components)).with_for_update())
        if item is None:
            raise HTTPException(404, "POS item not found")
        if body.not_kitchen and body.components:
            raise error(422, "An item marked 'not kitchen' cannot have a norm", "not_kitchen_with_norm")
        ids = [c.product_id for c in body.components]
        if len(set(ids)) != len(ids):
            raise error(422, "Each product can appear only once in a norm", "duplicate_product")
        products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))}
        missing = [i for i in ids if i not in products or not products[i].is_active]
        if missing:
            raise error(422, "Unknown or inactive product(s)", "inactive_product", product_ids=missing)
        comps = []
        for c in body.components:
            p = products[c.product_id]
            try:
                q = to_base(c.qty, c.qty_unit or p.unit, p.unit, p.base_unit, p.unit_size)
            except UnitError as e:
                raise error(422, str(e), "bad_unit", product_id=p.id) from None
            if q <= 0:
                raise error(422, f"The quantity of '{p.name}' rounds to zero", "zero_qty", product_id=p.id)
            comps.append(PosItemComponent(product_id=p.id, qty_base=q))
        item.not_kitchen = body.not_kitchen
        item.components = []
        db.flush()  # delete the old rows first: a product kept in the norm reuses the same primary key
        item.components = comps
        item.updated_at = func.now()
        db.flush()
        return item

    item = _run(db, apply)
    db.refresh(item)
    return _item_out(db, item)
