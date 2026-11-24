"""Inventory counts (requirements 2.5, docs/architecture.md section 5).

Lock order: inventory row -> products (FOR SHARE, ordered by id) -> inventory lines / stock balances.
Completion takes the inventory FOR UPDATE, then products, then the balances of every counted pair, and only
then writes status='completed'; documents that check "absorbed by an inventory" (reversal A1, backdating) run
their checks under the same balance locks, so they always see a completed inventory (no TOCTOU).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.units import QTY_QUANT, UnitError, to_base
from app.models import (
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
from app.services.posting import MAX_BALANCE, Delta, _lock_balances, _lock_products, _post, current_cost, db_now, error


# ------------------------------------------------------------------ helpers
def expected_at(db: Session, product_id: int, location_id: int, moment: datetime) -> Decimal:
    """Physical stock of a pair at `moment`: the sum of movements whose EVENT date is not later.

    Uses doc_date (when it happened), not created_at (when it was typed in): a reversal carries its
    original's date and a backdated receipt its real date, so both land on the right side of the count.
    """
    v = db.scalar(
        select(func.coalesce(func.sum(StockMovement.delta_base), 0)).where(
            StockMovement.product_id == product_id,
            StockMovement.location_id == location_id,
            StockMovement.doc_date <= moment,
        )
    )
    return Decimal(v).quantize(QTY_QUANT)


def _balance(db: Session, product_id: int, location_id: int) -> Decimal:
    v = db.scalar(select(StockBalance.qty_base).where(StockBalance.product_id == product_id, StockBalance.location_id == location_id))
    return Decimal(v or 0)


def _lock_inventory(db: Session, inventory_id: int, exclusive: bool) -> Inventory:
    stmt = select(Inventory).where(Inventory.id == inventory_id)
    stmt = stmt.with_for_update() if exclusive else stmt.with_for_update(read=True)
    inv = db.scalar(stmt.execution_options(populate_existing=True))
    if inv is None:
        raise error(404, "Inventory not found", "not_found")
    if inv.status != InventoryStatus.in_progress:
        raise error(409, f"Inventory is already {inv.status.value}", "inventory_closed")
    return inv


# -------------------------------------------------------------------- start
def start(db: Session, user: User, location_id: int, comment: str) -> Inventory:
    loc = db.get(Location, location_id)
    if loc is None or not loc.is_active:
        raise error(422, "Unknown or inactive location", "inactive_location")
    inv = Inventory(location_id=location_id, comment=comment, started_by=user.id, status=InventoryStatus.in_progress)
    db.add(inv)
    db.flush()  # the partial unique index rejects a second inventory in progress for this location
    # Lines: every active product that has a balance row here, including zero and negative balances
    # (a product that ran out is still expected on that shelf).
    rows = db.execute(
        select(StockBalance.product_id, StockBalance.qty_base)
        .join(Product, Product.id == StockBalance.product_id)
        .where(StockBalance.location_id == location_id, Product.is_active)
        .order_by(StockBalance.product_id)
    ).all()
    db.add_all(InventoryLine(inventory_id=inv.id, product_id=pid, expected_at_start_base=qty, version=1) for pid, qty in rows)
    db.flush()
    return inv


# -------------------------------------------------------------------- count
def count_line(
    db: Session,
    user: User,
    inventory_id: int,
    product_id: int,
    parts: list[tuple[Decimal, str | None]],
    counted_at: datetime | None,
    sent_at: datetime | None,
    version: int | None,
) -> InventoryLine:
    inv = _lock_inventory(db, inventory_id, exclusive=False)  # completion waits for us, and we for it
    p = _lock_products(db, [product_id])[product_id]  # FOR SHARE: units cannot change under us

    total = Decimal(0)
    for qty, unit in parts:
        try:
            total += to_base(qty, unit or p.unit, p.unit, p.base_unit, p.unit_size)
        except UnitError as e:
            raise error(422, str(e), "bad_unit", product_id=p.id) from None
    total = total.quantize(QTY_QUANT)
    if total > MAX_BALANCE:
        raise error(422, "Counted quantity is too large", "qty_too_large", product_id=p.id)

    # The moment of counting: the device's "counted" time, shifted by the device's clock error
    # (server_now - sent_at), clamped to [started_at, now]. A late upload keeps its real counting time.
    now = db_now(db)
    moment = counted_at or now
    if counted_at is not None and sent_at is not None:
        moment = counted_at + (now - sent_at)
    moment = min(max(moment, inv.started_at), now)

    line = db.scalar(
        select(InventoryLine)
        .where(InventoryLine.inventory_id == inv.id, InventoryLine.product_id == p.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if line is None:  # a product found on the shelf that was not in the snapshot
        if version not in (None, 0):
            raise error(409, "This line was removed or never existed; reload the count", "version_conflict")
        line = InventoryLine(inventory_id=inv.id, product_id=p.id, expected_at_start_base=_balance(db, p.id, inv.location_id), version=0)
        db.add(line)
    elif version is not None and version != line.version:
        raise error(409, "Someone else updated this line; reload to see their count", "version_conflict", current_version=line.version)

    line.counted_base = total
    line.counted_at = moment
    line.counted_by = user.id
    line.expected_at_count_base = expected_at(db, p.id, inv.location_id, moment)  # display only; recomputed on completion
    line.version = (line.version or 0) + 1
    db.flush()
    return line


def clear_count(db: Session, inventory_id: int, product_id: int, version: int | None) -> InventoryLine:
    inv = _lock_inventory(db, inventory_id, exclusive=False)
    line = db.scalar(
        select(InventoryLine).where(InventoryLine.inventory_id == inv.id, InventoryLine.product_id == product_id).with_for_update()
    )
    if line is None:
        raise error(404, "Line not found", "not_found")
    if version is not None and version != line.version:
        raise error(409, "Someone else updated this line; reload to see their count", "version_conflict", current_version=line.version)
    line.counted_base = line.counted_at = line.counted_by = line.expected_at_count_base = None
    line.version += 1
    db.flush()
    return line


# ----------------------------------------------------------------- complete
def complete(db: Session, user: User, inventory_id: int, zero_uncounted: bool) -> Inventory:
    inv = _lock_inventory(db, inventory_id, exclusive=True)
    lines = list(db.scalars(select(InventoryLine).where(InventoryLine.inventory_id == inv.id).order_by(InventoryLine.product_id).with_for_update()))
    counted = [line for line in lines if line.counted_base is not None or zero_uncounted]
    if not any(line.counted_base is not None for line in lines) and not (zero_uncounted and lines):
        raise error(422, "Nothing has been counted yet", "nothing_counted")

    products = _lock_products_any(db, [line.product_id for line in counted])
    # Lock the balances BEFORE marking the inventory completed: reversals and backdated documents check
    # "absorbed by a completed inventory" under these same locks.
    _lock_balances(db, [(line.product_id, inv.location_id) for line in counted])
    # Read the clock only now, after the locks: transactions that held them have committed, so this moment
    # orders correctly against their posted_at (reply 17, P1). now() would be our transaction start.
    now = db.scalar(select(func.clock_timestamp()))

    if zero_uncounted:  # explicit admin choice: "not found on the shelf" means zero
        for line in counted:
            if line.counted_base is None:
                line.counted_base, line.counted_at, line.counted_by = Decimal(0), now, user.id
                line.version += 1

    deltas: list[Delta] = []
    doc_lines: list[StockDocumentLine] = []
    for line in counted:
        p = products[line.product_id]
        expected = expected_at(db, p.id, inv.location_id, line.counted_at)  # recomputed now, see section 5
        cost = current_cost(p)
        line.expected_at_count_base = expected
        line.unit_cost_base = cost
        delta = (line.counted_base - expected).quantize(QTY_QUANT)
        if delta != 0:
            deltas.append(Delta(p.id, inv.location_id, delta, cost))
            doc_lines.append(
                StockDocumentLine(
                    line_no=len(doc_lines) + 1,
                    product_id=p.id,
                    location_from_id=inv.location_id if delta < 0 else None,
                    location_to_id=inv.location_id if delta > 0 else None,
                    qty_base=delta,  # signed for adjustments
                    unit_cost_base=cost,
                )
            )
    db.flush()

    doc_id = None
    if deltas:
        doc = StockDocument(
            id=uuid.uuid4(),
            type=DocType.inventory_adjustment,
            doc_date=now,
            comment=f"Inventory #{inv.id}",
            created_by=user.id,
            allow_negative=False,
        )
        doc.lines = doc_lines
        # The adjustment makes the balance equal the count; it is exempt from the negative-stock check.
        _post(db, user, doc, deltas, check_negative=False)
        doc_id = doc.id

    done = db.execute(
        update(Inventory)
        .where(Inventory.id == inv.id, Inventory.status == InventoryStatus.in_progress)
        .values(status=InventoryStatus.completed, completed_at=now, completed_by=user.id, adjustment_document_id=doc_id)
        .returning(Inventory.id)
    ).first()
    if done is None:  # cannot happen while we hold the row lock; kept as a guard
        raise error(409, "Inventory is already closed", "inventory_closed")
    db.flush()
    db.refresh(inv)
    return inv


def _lock_products_any(db: Session, ids: list[int]) -> dict[int, Product]:
    """Like posting._lock_products but allows inactive products: a deactivated product found on the shelf
    must still be adjusted."""
    rows = db.scalars(select(Product).where(Product.id.in_(sorted(set(ids)))).order_by(Product.id).with_for_update(read=True))
    return {p.id: p for p in rows}


def cancel(db: Session, user: User, inventory_id: int) -> Inventory:
    inv = _lock_inventory(db, inventory_id, exclusive=True)
    db.execute(
        update(Inventory)
        .where(Inventory.id == inv.id, Inventory.status == InventoryStatus.in_progress)
        .values(status=InventoryStatus.cancelled, completed_at=func.clock_timestamp(), completed_by=user.id)
    )
    db.flush()
    db.refresh(inv)
    return inv
