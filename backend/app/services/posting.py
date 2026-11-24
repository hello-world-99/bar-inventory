"""Posting of stock documents (docs/architecture.md section 4).

Every public function runs inside the caller's transaction and leaves the commit to the caller.

Lock order, identical everywhere (no deadlocks):
  1. products  - FOR SHARE (FOR UPDATE for receipts, which update purchase_price), ordered by id;
                 serializes posting with update_product, so unit_size cannot change under us;
  2. balances  - INSERT .. ON CONFLICT DO NOTHING, then FOR UPDATE, ordered by (product_id, location_id).

Write order: the document and its lines are inserted as a draft with all fields final, then flipped
to 'posted' (database triggers make posted documents and their lines immutable), then balances and
append-only movements are written.
"""

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import exists, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.permissions import Perm, has_perm
from app.core.units import QTY_QUANT, UnitError, to_base
from app.models import (
    DocStatus,
    DocType,
    Inventory,
    InventoryLine,
    InventoryStatus,
    Location,
    Product,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockMovement,
    User,
)
from app.schemas_docs import QtyIn, ReceiptIn, ReverseIn, TransferIn, WriteOffIn

COST_QUANT = Decimal("0.000001")  # NUMERIC(18,6)
CLOCK_SKEW = timedelta(minutes=5)
MAX_AGE = timedelta(days=366)  # catches typos like 1925 instead of 2025
MAX_LINE_QTY_BASE = Decimal("1000000000")  # 10^9 base units per line
MAX_BALANCE = Decimal("99999999999.999")  # NUMERIC(14,3)
REVERSIBLE = {DocType.receipt, DocType.write_off, DocType.transfer}


def error(code: int, message: str, kind: str, **extra: Any) -> HTTPException:
    """Errors carry a machine-readable `code` so clients can react (e.g. offer allow_negative)."""
    return HTTPException(code, {"code": kind, "message": message, **extra})


@dataclass(frozen=True)
class Delta:
    product_id: int
    location_id: int
    delta: Decimal
    unit_cost_base: Decimal


# ---------------------------------------------------------------- idempotency
def request_hash(kind: str, body: BaseModel) -> str:
    canonical = json.dumps({"kind": kind, **body.model_dump(mode="json")}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def find_existing(db: Session, doc_id: uuid.UUID, req_hash: str) -> StockDocument | None:
    """Same id + same body -> the stored document (retry). Same id + different body -> 409."""
    doc = db.get(StockDocument, doc_id)
    if doc is None:
        return None
    if doc.request_hash != req_hash:
        raise error(status.HTTP_409_CONFLICT, "A different document with this id already exists", "id_conflict")
    return doc


# -------------------------------------------------------------------- helpers
def _lock_products(db: Session, ids: Iterable[int], exclusive: bool = False) -> dict[int, Product]:
    ids = sorted(set(ids))
    stmt = select(Product).where(Product.id.in_(ids)).order_by(Product.id)
    stmt = stmt.with_for_update() if exclusive else stmt.with_for_update(read=True)
    found = {p.id: p for p in db.scalars(stmt)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise error(422, f"Unknown product(s): {missing}", "unknown_product", product_ids=missing)
    inactive = [p.id for p in found.values() if not p.is_active]
    if inactive:
        raise error(422, "Inactive products cannot be used in new documents", "inactive_product", product_ids=inactive)
    return found


def _check_locations(db: Session, ids: Iterable[int]) -> dict[int, Location]:
    ids = sorted(set(ids))
    found = {loc.id: loc for loc in db.scalars(select(Location).where(Location.id.in_(ids)))}
    bad = [i for i in ids if i not in found or not found[i].is_active]
    if bad:
        raise error(422, "Unknown or inactive location(s)", "inactive_location", location_ids=bad)
    return found


def _qty_base(line: QtyIn, p: Product) -> Decimal:
    try:
        q = to_base(line.qty, line.qty_unit or p.unit, p.unit, p.base_unit, p.unit_size)
    except UnitError as e:
        raise error(422, str(e), "bad_unit", product_id=p.id) from None
    if q <= 0:
        raise error(422, f"Quantity of product {p.id} rounds to zero", "zero_qty", product_id=p.id)
    if q > MAX_LINE_QTY_BASE:
        raise error(422, f"Quantity of product {p.id} is too large", "qty_too_large", product_id=p.id)
    return q


def current_cost(p: Product) -> Decimal:
    return (p.purchase_price / p.unit_size).quantize(COST_QUANT)


def db_now(db: Session) -> datetime:
    return db.scalar(select(func.now()))  # transaction timestamp, same as movements.created_at


def check_date_bounds(doc_date: datetime, now: datetime) -> None:
    if doc_date > now + CLOCK_SKEW:
        raise error(422, "Document date cannot be in the future", "future_date")
    if doc_date < now - MAX_AGE:
        raise error(422, "Document date is more than a year in the past", "date_too_old")


def check_backdate(db: Session, user: User, doc_date: datetime, pairs: Iterable[tuple[int, int]], confirm: bool) -> bool:
    """Must run AFTER the balances of `pairs` are locked (completing an inventory locks the same rows).

    A document is a problem only for (product, location) pairs that a COMPLETED inventory counted at or after
    the document's date: that count already contains the document physically, so posting it now would count
    it twice. Pairs counted by an inventory still in progress are fine - completion recomputes the expected
    quantity from doc_date (architecture section 5). Returns True when an admin confirmed such a backdate.
    """
    hit = db.execute(
        select(Product.name, Location.name, InventoryLine.counted_at)
        .join(Inventory, Inventory.id == InventoryLine.inventory_id)
        .join(Product, Product.id == InventoryLine.product_id)
        .join(Location, Location.id == Inventory.location_id)
        .where(
            Inventory.status == InventoryStatus.completed,
            InventoryLine.counted_base.is_not(None),
            InventoryLine.counted_at >= doc_date,
            tuple_(InventoryLine.product_id, Inventory.location_id).in_(sorted(set(pairs))),
        )
        .order_by(InventoryLine.counted_at.desc())
        .limit(1)
    ).first()
    if hit is None:
        return False
    msg = f"'{hit[0]}' at '{hit[1]}' was counted on {hit[2].isoformat()}, after this document's date"
    if not has_perm(user.role, Perm.backdate):
        raise error(422, msg + "; only an administrator can post such a document", "backdate_forbidden")
    if not confirm:
        raise error(422, msg + "; confirm to post it anyway", "backdate_confirmation_required")
    return True


def _lock_balances(db: Session, pairs: Sequence[tuple[int, int]]) -> dict[tuple[int, int], StockBalance]:
    pairs = sorted(set(pairs))
    db.execute(
        pg_insert(StockBalance)
        .values([{"product_id": p, "location_id": loc, "qty_base": 0} for p, loc in pairs])
        .on_conflict_do_nothing()
    )
    rows = db.scalars(
        select(StockBalance)
        .where(tuple_(StockBalance.product_id, StockBalance.location_id).in_(pairs))
        .order_by(StockBalance.product_id, StockBalance.location_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {(b.product_id, b.location_id): b for b in rows}


def _post(
    db: Session,
    user: User,
    doc: StockDocument,
    deltas: list[Delta],
    *,
    check_negative: bool,
    allow_negative_requested: bool = False,
    pre_check: Callable[[list[tuple[int, int]]], None] | None = None,
) -> StockDocument:
    pairs = sorted({(d.product_id, d.location_id) for d in deltas})
    balances = _lock_balances(db, pairs)
    # Checks that depend on other transactions (inventory completion) run only now, under the balance locks:
    # under READ COMMITTED they see anything committed by whoever held the locks before us.
    if pre_check is not None:
        pre_check(pairs)

    # Simulate first so that the document's own fields are final before it becomes immutable.
    running = {k: b.qty_base for k, b in balances.items()}
    after: list[Decimal] = []
    shortages: dict[tuple[int, int], dict[str, Any]] = {}
    for d in deltas:
        key = (d.product_id, d.location_id)
        before = running[key]
        running[key] = (before + d.delta).quantize(QTY_QUANT)
        if abs(running[key]) > MAX_BALANCE:
            raise error(422, "Resulting balance is too large", "qty_too_large", product_id=d.product_id)
        after.append(running[key])
        if check_negative and d.delta < 0 and running[key] < 0:
            s = shortages.setdefault(
                key, {"product_id": d.product_id, "location_id": d.location_id, "available": str(balances[key].qty_base), "requested": Decimal(0)}
            )
            s["requested"] -= d.delta
    if shortages:
        items = [s | {"requested": str(s["requested"])} for s in shortages.values()]
        if not allow_negative_requested:
            can = has_perm(user.role, Perm.allow_negative)
            raise error(
                422,
                "Not enough stock" + ("; confirm to allow a negative balance" if can else ""),
                "insufficient_stock",
                items=items,
                can_override=can,
            )
        if not has_perm(user.role, Perm.allow_negative):
            raise error(403, "Only an administrator can allow a negative balance", "negative_forbidden", items=items)
        doc.allow_negative = True

    doc.status = DocStatus.draft
    db.add(doc)
    db.flush()
    flipped = db.execute(
        update(StockDocument)
        .where(StockDocument.id == doc.id, StockDocument.status == DocStatus.draft)
        # clock_timestamp(), not now(): now() is the transaction START, which for transactions that queued
        # on the balance locks does not match the order in which their effects became visible. Taken after
        # the locks, posted_at orders correctly against inventory completed_at (reversal check A1).
        .values(status=DocStatus.posted, posted_by=user.id, posted_at=func.clock_timestamp())
        .returning(StockDocument.id)
    ).first()
    if flipped is None:
        raise error(409, "Document is already posted", "already_posted")

    for d, bal_after in zip(deltas, after, strict=True):
        db.add(
            StockMovement(
                document_id=doc.id,
                product_id=d.product_id,
                location_id=d.location_id,
                delta_base=d.delta,
                unit_cost_base=d.unit_cost_base,
                balance_after=bal_after,
                doc_date=doc.doc_date,
                user_id=user.id,
            )
        )
    for key, value in running.items():
        balances[key].qty_base = value
    db.flush()
    db.refresh(doc)
    return doc


def _new_doc(body, doc_type: DocType, user: User, doc_date: datetime, req_hash: str, **fields: Any) -> StockDocument:
    return StockDocument(
        id=body.id,
        type=doc_type,
        doc_date=doc_date,
        comment=getattr(body, "comment", ""),
        created_by=user.id,
        request_hash=req_hash,
        allow_negative=False,
        **fields,
    )


def _backdate_hook(db: Session, user: User, doc: StockDocument, confirm: bool) -> Callable[[list[tuple[int, int]]], None]:
    def hook(pairs: list[tuple[int, int]]) -> None:
        doc.backdate_confirmed = check_backdate(db, user, doc.doc_date, pairs, confirm)

    return hook


# ------------------------------------------------------------------ documents
def post_receipt(db: Session, user: User, body: ReceiptIn, req_hash: str) -> StockDocument:
    now = db_now(db)
    doc_date = body.doc_date or now
    check_date_bounds(doc_date, now)
    _check_locations(db, (line.location_id for line in body.lines))
    products = _lock_products(db, (line.product_id for line in body.lines), exclusive=True)

    lines, deltas = [], []
    for i, line in enumerate(body.lines, 1):
        p = products[line.product_id]
        qty = _qty_base(line, p)
        cost = (line.unit_price / p.unit_size).quantize(COST_QUANT)
        lines.append(StockDocumentLine(line_no=i, product_id=p.id, location_to_id=line.location_id, qty_base=qty, unit_price=line.unit_price, unit_cost_base=cost))
        deltas.append(Delta(p.id, line.location_id, qty, cost))

    doc = _new_doc(body, DocType.receipt, user, doc_date, req_hash, supplier=body.supplier or None, invoice_no=body.invoice_no or None)
    doc.lines = lines
    _post(db, user, doc, deltas, check_negative=False, pre_check=_backdate_hook(db, user, doc, body.confirm_backdate))

    # Latest price wins, but a backdated receipt never overrides a newer price (architecture section 4).
    for line in body.lines:
        p = products[line.product_id]
        if p.price_updated_at is None or doc_date >= p.price_updated_at:
            p.purchase_price = line.unit_price
            p.price_updated_at = doc_date
    db.flush()
    return doc


def post_write_off(db: Session, user: User, body: WriteOffIn, req_hash: str) -> StockDocument:
    now = db_now(db)
    doc_date = body.doc_date or now
    check_date_bounds(doc_date, now)
    _check_locations(db, (line.location_id for line in body.lines))
    products = _lock_products(db, (line.product_id for line in body.lines))

    lines, deltas = [], []
    for i, line in enumerate(body.lines, 1):
        p = products[line.product_id]
        qty, cost = _qty_base(line, p), current_cost(p)
        lines.append(StockDocumentLine(line_no=i, product_id=p.id, location_from_id=line.location_id, qty_base=qty, unit_cost_base=cost))
        deltas.append(Delta(p.id, line.location_id, -qty, cost))

    doc = _new_doc(body, DocType.write_off, user, doc_date, req_hash, reason=body.reason)
    doc.lines = lines
    return _post(db, user, doc, deltas, check_negative=True, allow_negative_requested=body.allow_negative,
                 pre_check=_backdate_hook(db, user, doc, body.confirm_backdate))


def post_transfer(db: Session, user: User, body: TransferIn, req_hash: str) -> StockDocument:
    if body.from_location_id == body.to_location_id:
        raise error(422, "Source and destination must differ", "same_location")
    now = db_now(db)
    doc_date = body.doc_date or now
    locs = {body.from_location_id, body.to_location_id}
    check_date_bounds(doc_date, now)
    _check_locations(db, locs)
    products = _lock_products(db, (line.product_id for line in body.lines))

    lines, deltas = [], []
    for i, line in enumerate(body.lines, 1):
        p = products[line.product_id]
        qty, cost = _qty_base(line, p), current_cost(p)
        lines.append(StockDocumentLine(line_no=i, product_id=p.id, location_from_id=body.from_location_id, location_to_id=body.to_location_id, qty_base=qty, unit_cost_base=cost))
        deltas += [Delta(p.id, body.from_location_id, -qty, cost), Delta(p.id, body.to_location_id, qty, cost)]

    doc = _new_doc(body, DocType.transfer, user, doc_date, req_hash)
    doc.lines = lines
    return _post(db, user, doc, deltas, check_negative=True, allow_negative_requested=body.allow_negative,
                 pre_check=_backdate_hook(db, user, doc, body.confirm_backdate))


def reverse(db: Session, user: User, original_id: uuid.UUID, body: ReverseIn, req_hash: str) -> StockDocument:
    orig = db.get(StockDocument, original_id, with_for_update=True)  # serializes concurrent reversals
    if orig is None:
        raise error(404, "Document not found", "not_found")
    if orig.status != DocStatus.posted or orig.type not in REVERSIBLE:
        raise error(422, "Only posted receipts, write-offs and transfers can be reversed", "not_reversible")
    if db.scalar(select(exists().where(StockDocument.reversal_of == orig.id))):
        raise error(409, "This document has already been reversed", "already_reversed")

    movements = list(db.scalars(select(StockMovement).where(StockMovement.document_id == orig.id).order_by(StockMovement.id)))

    def absorbed_by_inventory(pairs: list[tuple[int, int]]) -> None:
        """A1, evaluated under the balance locks. A completed inventory absorbed the original when it was
        completed after the original was posted (its expected quantity included it) and counted the pair at
        or after the original's date. Checked on inventory lines, not on adjustment movements: a count that
        matched (delta 0) produces no movement but still absorbed the document."""
        hit = db.execute(
            select(InventoryLine.product_id, Inventory.location_id)
            .join(Inventory, Inventory.id == InventoryLine.inventory_id)
            .where(
                Inventory.status == InventoryStatus.completed,
                Inventory.completed_at > orig.posted_at,
                InventoryLine.counted_base.is_not(None),
                InventoryLine.counted_at >= orig.doc_date,
                tuple_(InventoryLine.product_id, Inventory.location_id).in_(pairs),
            )
            .limit(1)
        ).first()
        if hit:
            raise error(
                409,
                "An inventory completed after this document already counted the affected stock; correct it with a new inventory",
                "counted_after",
                product_id=hit[0],
                location_id=hit[1],
            )

    # No product lock needed: the products already have movements, so their units are frozen.
    lines, deltas = [], []
    for i, m in enumerate(movements, 1):
        mirror = -m.delta_base
        lines.append(
            StockDocumentLine(
                line_no=i,
                product_id=m.product_id,
                location_from_id=m.location_id if mirror < 0 else None,
                location_to_id=m.location_id if mirror > 0 else None,
                qty_base=abs(mirror),
                unit_cost_base=m.unit_cost_base,
            )
        )
        deltas.append(Delta(m.product_id, m.location_id, mirror, m.unit_cost_base))

    # A reversal corrects a record rather than describing a new physical event, so it carries the
    # original's date: an inventory in progress then nets the original and its reversal out (section 5).
    doc = StockDocument(
        id=body.id,
        type=DocType.reversal,
        doc_date=orig.doc_date,
        comment=body.comment,
        reversal_of=orig.id,
        created_by=user.id,
        request_hash=req_hash,
        allow_negative=False,
    )
    doc.lines = lines
    return _post(db, user, doc, deltas, check_negative=True, allow_negative_requested=body.allow_negative,
                 pre_check=absorbed_by_inventory)
