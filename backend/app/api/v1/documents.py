"""Receipts, write-offs, transfers, reversals (2.3, 2.4, 2.6), the movement journal (2.7) and stock balances."""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, aliased

from app.api.deps import DbSession, require
from app.api.errors import constraint_name
from app.api.v1.settings import load_settings
from app.core.permissions import Perm
from app.models import (
    Category,
    DocType,
    Inventory,
    Location,
    Product,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockMovement,
    User,
)
from app.schemas_docs import (
    DocLineOut,
    DocOut,
    DocPage,
    DocSummary,
    MovementOut,
    MovementPage,
    ReceiptIn,
    ReconcileRow,
    ReverseIn,
    ReverseKey,
    StockRow,
    TransferIn,
    WriteOffIn,
)
from app.services import posting

router = APIRouter(tags=["documents"])
Viewer = Annotated[User, Depends(require(Perm.view))]


# ------------------------------------------------------------------ helpers
def business_range(db: Session, date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    """Operational days: a day runs from settings.business_day_starts_at to the same time next day (bars close after midnight)."""
    s = load_settings(db)
    tz, start = ZoneInfo(s.timezone), s.business_day_starts_at
    lo = datetime.combine(date_from, start, tz) if date_from else None
    hi = datetime.combine(date_to + timedelta(days=1), start, tz) if date_to else None
    return lo, hi


def doc_out(db: Session, doc: StockDocument) -> DocOut:
    lf, lt = aliased(Location), aliased(Location)
    rows = db.execute(
        select(StockDocumentLine, Product, lf.name, lt.name)
        .join(Product, Product.id == StockDocumentLine.product_id)
        .outerjoin(lf, lf.id == StockDocumentLine.location_from_id)
        .outerjoin(lt, lt.id == StockDocumentLine.location_to_id)
        .where(StockDocumentLine.document_id == doc.id)
        .order_by(StockDocumentLine.line_no)
    ).all()
    lines = []
    for line, p, from_name, to_name in rows:
        amount = abs(line.qty_base) * (line.unit_cost_base or Decimal(0))
        lines.append(
            DocLineOut(
                line_no=line.line_no, product_id=p.id, product_name=p.name, product_sku=p.sku, unit=p.unit,
                base_unit=p.base_unit, unit_size=p.unit_size, location_from_id=line.location_from_id,
                location_from_name=from_name, location_to_id=line.location_to_id, location_to_name=to_name,
                qty_base=line.qty_base, unit_price=line.unit_price, unit_cost_base=line.unit_cost_base, amount=amount,
            )
        )
    return DocOut(
        id=doc.id, type=doc.type, status=doc.status, doc_date=doc.doc_date, reason=doc.reason, supplier=doc.supplier,
        invoice_no=doc.invoice_no, comment=doc.comment, reversal_of=doc.reversal_of,
        reversed_by=db.scalar(select(StockDocument.id).where(StockDocument.reversal_of == doc.id)),
        allow_negative=doc.allow_negative, backdate_confirmed=doc.backdate_confirmed, created_by=doc.created_by,
        created_by_name=db.scalar(select(func.coalesce(func.nullif(User.full_name, ""), User.username)).where(User.id == doc.created_by)) or "",
        created_at=doc.created_at, posted_at=doc.posted_at,
        inventory_id=db.scalar(select(Inventory.id).where(Inventory.adjustment_document_id == doc.id)),
        total_amount=sum((line.amount for line in lines), Decimal(0)), lines=lines,
    )


def _create(
    db: Session, response: Response, user: User, kind: str, body: BaseModel, doc_id: uuid.UUID,
    post: Callable[[str], StockDocument],
) -> DocOut:
    """Create-and-post with idempotent retries keyed by the client-generated document id."""
    h = posting.request_hash(kind, body)
    existing = posting.find_existing(db, doc_id, h)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return doc_out(db, existing)
    try:
        doc = post(h)
        db.commit()
    except IntegrityError as e:  # a concurrent request with the same id won the race
        db.rollback()
        if constraint_name(e) != "stock_documents_pkey":
            raise
        existing = posting.find_existing(db, doc_id, h)
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return doc_out(db, existing)
    except HTTPException:
        db.rollback()
        raise
    except DataError:  # numeric overflow etc. that slipped past validation: a client error, never a 500
        db.rollback()
        raise HTTPException(422, {"code": "invalid_value", "message": "A value is out of the supported range"}) from None
    response.status_code = status.HTTP_201_CREATED
    return doc_out(db, doc)


# ---------------------------------------------------------------- documents
@router.post("/receipts", response_model=DocOut, status_code=201)
def create_receipt(body: ReceiptIn, response: Response, db: DbSession, user: Annotated[User, Depends(require(Perm.post_receipt))]) -> DocOut:
    return _create(db, response, user, "receipt", body, body.id, lambda h: posting.post_receipt(db, user, body, h))


@router.post("/write-offs", response_model=DocOut, status_code=201)
def create_write_off(body: WriteOffIn, response: Response, db: DbSession, user: Annotated[User, Depends(require(Perm.post_write_off))]) -> DocOut:
    return _create(db, response, user, "write_off", body, body.id, lambda h: posting.post_write_off(db, user, body, h))


@router.post("/transfers", response_model=DocOut, status_code=201)
def create_transfer(body: TransferIn, response: Response, db: DbSession, user: Annotated[User, Depends(require(Perm.post_transfer))]) -> DocOut:
    return _create(db, response, user, "transfer", body, body.id, lambda h: posting.post_transfer(db, user, body, h))


@router.post("/documents/{doc_id}/reverse", response_model=DocOut, status_code=201)
def reverse_document(
    doc_id: uuid.UUID, body: ReverseIn, response: Response, db: DbSession,
    user: Annotated[User, Depends(require(Perm.reverse_document))],
) -> DocOut:
    keyed = ReverseKey(original=doc_id, body=body)  # the same reversal id must target the same document
    return _create(db, response, user, "reversal", keyed, body.id, lambda h: posting.reverse(db, user, doc_id, body, h))


@router.get("/documents/{doc_id}", response_model=DocOut)
def get_document(doc_id: uuid.UUID, _: Viewer, db: DbSession) -> DocOut:
    doc = db.get(StockDocument, doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc_out(db, doc)


@router.get("/documents", response_model=DocPage)
def list_documents(
    _: Viewer,
    db: DbSession,
    type: Annotated[list[DocType] | None, Query()] = None,  # noqa: A002
    date_from: date | None = None,
    date_to: date | None = None,
    product_id: int | None = None,
    location_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocPage:
    lo, hi = business_range(db, date_from, date_to)
    reversal = aliased(StockDocument)
    totals = (
        select(
            StockDocumentLine.document_id,
            func.count().label("n"),
            func.sum(func.abs(StockDocumentLine.qty_base) * func.coalesce(StockDocumentLine.unit_cost_base, 0)).label("amount"),
        )
        .group_by(StockDocumentLine.document_id)
        .subquery()
    )
    stmt = (
        select(StockDocument, totals.c.n, totals.c.amount, reversal.id, func.coalesce(func.nullif(User.full_name, ""), User.username))
        .join(totals, totals.c.document_id == StockDocument.id)
        .join(User, User.id == StockDocument.created_by)
        .outerjoin(reversal, reversal.reversal_of == StockDocument.id)
    )
    if type:
        stmt = stmt.where(StockDocument.type.in_(type))
    if lo:
        stmt = stmt.where(StockDocument.doc_date >= lo)
    if hi:
        stmt = stmt.where(StockDocument.doc_date < hi)
    if product_id is not None or location_id is not None:
        conds = [StockDocumentLine.document_id == StockDocument.id]
        if product_id is not None:
            conds.append(StockDocumentLine.product_id == product_id)
        if location_id is not None:
            conds.append(or_(StockDocumentLine.location_from_id == location_id, StockDocumentLine.location_to_id == location_id))
        stmt = stmt.where(select(StockDocumentLine.id).where(and_(*conds)).exists())
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.order_by(StockDocument.doc_date.desc(), StockDocument.created_at.desc()).limit(limit).offset(offset))
    return DocPage(
        total=total,
        items=[
            DocSummary(
                id=d.id, type=d.type, doc_date=d.doc_date, reason=d.reason, supplier=d.supplier, invoice_no=d.invoice_no,
                comment=d.comment, reversal_of=d.reversal_of, reversed_by=rev, created_by_name=name, posted_at=d.posted_at,
                line_count=n, total_amount=amount or Decimal(0),
            )
            for d, n, amount, rev, name in rows
        ],
    )


# ------------------------------------------------------------------ journal
@router.get("/journal", response_model=MovementPage)
def journal(
    _: Viewer,
    db: DbSession,
    type: Annotated[list[DocType] | None, Query()] = None,  # noqa: A002
    date_from: date | None = None,
    date_to: date | None = None,
    product_id: int | None = None,
    location_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MovementPage:
    lo, hi = business_range(db, date_from, date_to)
    stmt = (
        select(StockMovement, StockDocument, Product, Location.name, func.coalesce(func.nullif(User.full_name, ""), User.username))
        .join(StockDocument, StockDocument.id == StockMovement.document_id)
        .join(Product, Product.id == StockMovement.product_id)
        .join(Location, Location.id == StockMovement.location_id)
        .join(User, User.id == StockMovement.user_id)
    )
    if type:
        stmt = stmt.where(StockDocument.type.in_(type))
    if lo:
        stmt = stmt.where(StockMovement.doc_date >= lo)
    if hi:
        stmt = stmt.where(StockMovement.doc_date < hi)
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if location_id is not None:
        stmt = stmt.where(StockMovement.location_id == location_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.order_by(StockMovement.doc_date.desc(), StockMovement.id.desc()).limit(limit).offset(offset))
    return MovementPage(
        total=total,
        items=[
            MovementOut(
                id=m.id, document_id=d.id, doc_type=d.type, reason=d.reason, doc_date=m.doc_date, created_at=m.created_at,
                product_id=p.id, product_name=p.name, product_sku=p.sku, unit=p.unit, base_unit=p.base_unit,
                unit_size=p.unit_size, location_id=m.location_id, location_name=loc, delta_base=m.delta_base,
                balance_after=m.balance_after, unit_cost_base=m.unit_cost_base, amount=m.delta_base * m.unit_cost_base,
                user_name=user_name, comment=d.comment,
            )
            for m, d, p, loc, user_name in rows
        ],
    )


# -------------------------------------------------------------------- stock
@router.get("/stock", response_model=list[StockRow])
def stock(
    _: Viewer,
    db: DbSession,
    location_id: int | None = None,
    category_id: int | None = None,
    include_zero: bool = False,
) -> list[StockRow]:
    stmt = (
        select(StockBalance, Product, Category, Location.name)
        .join(Product, Product.id == StockBalance.product_id)
        .join(Category, Category.id == Product.category_id)
        .join(Location, Location.id == StockBalance.location_id)
    )
    if location_id is not None:
        stmt = stmt.where(StockBalance.location_id == location_id)
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if not include_zero:
        stmt = stmt.where(StockBalance.qty_base != 0)
    else:  # zero rows only matter for products and places still in use
        stmt = stmt.where(or_(StockBalance.qty_base != 0, and_(Product.is_active, Location.is_active)))
    stmt = stmt.order_by(func.lower(Product.name), func.lower(Location.name))
    return [
        StockRow(
            product_id=p.id, product_name=p.name, product_sku=p.sku, category_code=c.code, category_name=c.name,
            unit=p.unit, base_unit=p.base_unit, unit_size=p.unit_size, location_id=b.location_id, location_name=loc,
            qty_base=b.qty_base, value=b.qty_base * p.purchase_price / p.unit_size,
        )
        for b, p, c, loc in db.execute(stmt)
    ]


@router.get("/stock/reconcile", response_model=list[ReconcileRow])
def reconcile(_: Annotated[User, Depends(require(Perm.manage_settings))], db: DbSession) -> list[ReconcileRow]:
    """Invariant check: every balance equals the sum of its journal. An empty list means consistent."""
    sums = (
        select(StockMovement.product_id, StockMovement.location_id, func.sum(StockMovement.delta_base).label("s"))
        .group_by(StockMovement.product_id, StockMovement.location_id)
        .subquery()
    )
    rows = db.execute(
        select(StockBalance.product_id, StockBalance.location_id, StockBalance.qty_base, func.coalesce(sums.c.s, 0))
        .outerjoin(sums, and_(sums.c.product_id == StockBalance.product_id, sums.c.location_id == StockBalance.location_id))
        .where(StockBalance.qty_base != func.coalesce(sums.c.s, 0))
    )
    return [ReconcileRow(product_id=p, location_id=loc, balance=b, journal_sum=s) for p, loc, b, s in rows]

