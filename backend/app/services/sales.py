"""POS sales imports: upload -> usage by the norms -> write-off (agent-room replies 30-32).

Every public function runs inside the caller's transaction and leaves the commit to the caller.

Rules:
  * one active (not voided) report per business day, and the same sales (content hash) only once - both are
    unique indexes, so concurrent uploads cannot slip past the checks;
  * a draft shows the usage by the CURRENT norms; posting or covering freezes it in sales_import_usage;
  * the write-off is an ordinary 'write_off' document (reason 'sales') posted by posting.post_write_off, dated at
    the START of the sales business day. A product that a completed inventory counted at that location at or
    after that moment already lacks these sales in the count: it is skipped and marked as covered by that
    inventory (never "confirmed"); the rest is written off. Decided per product (reply 32 P3, reply 39 P2);
  * lock order: sales import row -> products -> balances (posting); inventory completion never locks imports.
"""

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from app.api.v1.settings import load_settings
from app.core.permissions import Perm, has_perm
from app.core.units import QTY_QUANT
from app.models import (
    Inventory,
    InventoryLine,
    InventoryStatus,
    Location,
    PosItem,
    Product,
    SalesImport,
    SalesImportLine,
    SalesImportStatus,
    SalesImportUsage,
    DocType,
    StockDocument,
    StockDocumentLine,
    Unit,
    User,
    WriteOffReason,
)
from app.schemas_docs import ReverseIn, ReverseKey, WriteOffIn, WriteOffLineIn
from app.schemas_sales import CorrectIn, PostIn, VoidIn
from app.services import posting
from app.services.pos_xlsx import PosLine, PosReport, content_hash, file_date_warning, parse
from app.services.posting import error

ACTIVE = SalesImport.status != SalesImportStatus.voided
DONE = (SalesImportStatus.posted, SalesImportStatus.covered)
MAX_AGE_DAYS = 366
PENDING_LIMIT = 31


# ------------------------------------------------------------ business days
def _day_settings(db: Session) -> tuple[ZoneInfo, time]:
    s = load_settings(db)
    return ZoneInfo(s.timezone), s.business_day_starts_at


def day_start(db: Session, d: date) -> datetime:
    tz, start = _day_settings(db)
    return datetime.combine(d, start, tz)


def current_business_day(db: Session) -> date:
    tz, start = _day_settings(db)
    local = posting.db_now(db).astimezone(tz)
    return local.date() - timedelta(days=1) if local.time() < start else local.date()


def default_sales_date(db: Session) -> date:
    return current_business_day(db) - timedelta(days=1)


# --------------------------------------------------------------------- usage
@dataclass
class Part:
    pos_code: str
    pos_name: str
    sold_qty: Decimal
    product_id: int
    per_unit_base: Decimal
    qty_base: Decimal
    covered_inventory_id: int | None = None  # skipped: a completed inventory already counted it
    covered_at: datetime | None = None
    unit_cost_base: Decimal | None = None


@dataclass
class Usage:
    parts: list[Part]
    unmapped: list[SalesImportLine]
    not_kitchen: list[SalesImportLine]

    def totals(self) -> dict[int, Decimal]:
        out: dict[int, Decimal] = defaultdict(Decimal)
        for p in self.parts:
            out[p.product_id] += p.qty_base
        return {k: v.quantize(QTY_QUANT) for k, v in out.items() if v > 0}


def _pos_items(db: Session, codes: list[str]) -> dict[str, PosItem]:
    rows = db.scalars(select(PosItem).options(selectinload(PosItem.components)).where(PosItem.code.in_(codes)))
    return {i.code: i for i in rows}


def compute_usage(db: Session, imp: SalesImport) -> Usage:
    items = _pos_items(db, [line.pos_code for line in imp.lines])
    frozen = imp.status in DONE
    used_codes = {u.pos_code for u in imp.usage}
    parts: list[Part] = []
    unmapped: list[SalesImportLine] = []
    not_kitchen: list[SalesImportLine] = []
    if frozen:
        parts = [Part(u.pos_code, u.pos_name, u.sold_qty, u.product_id, u.per_unit_base, u.qty_base, u.covered_inventory_id, u.covered_at,
                      u.unit_cost_base)
                 for u in imp.usage]
    for line in imp.lines:
        item = items.get(line.pos_code)
        if item is not None and item.not_kitchen:
            not_kitchen.append(line)
            continue
        if frozen:
            if line.pos_code not in used_codes and line.qty > 0:
                unmapped.append(line)
            continue
        if item is None or not item.components:
            if line.qty > 0:
                unmapped.append(line)
            continue
        sold = max(line.qty, Decimal(0))  # summed per code at parse time, then clamped (reply 32, N5)
        if sold == 0:
            continue
        for c in item.components:
            parts.append(Part(line.pos_code, line.pos_name, sold, c.product_id, c.qty_base, (sold * c.qty_base).quantize(QTY_QUANT)))
    return Usage(parts, unmapped, not_kitchen)


def _snapshot(imp: SalesImport, usage: Usage) -> None:
    imp.usage = [
        SalesImportUsage(pos_code=p.pos_code, pos_name=p.pos_name, sold_qty=p.sold_qty, product_id=p.product_id,
                         per_unit_base=p.per_unit_base, qty_base=p.qty_base, covered_inventory_id=p.covered_inventory_id,
                         covered_at=p.covered_at, unit_cost_base=p.unit_cost_base)
        for p in usage.parts
    ]


# -------------------------------------------------------------------- upload
def _active(db: Session, *cond) -> SalesImport | None:
    return db.scalar(select(SalesImport).where(ACTIVE, *cond).with_for_update())


def _match_known_codes(db: Session, report: PosReport) -> None:
    """A POS that writes codes as numbers drops leading zeros (1783 for 001783): map such codes to a known POS
    item with the same digits, so its norm still applies (reply 39, N2). Unknown codes stay as they are."""
    known = {c.lstrip("0"): c for c in db.scalars(select(PosItem.code)) if c.isdigit()}
    merged: dict[str, PosLine] = {}
    for line in report.lines:
        if line.code.isdigit() and line.code not in known.values():
            line.code = known.get(line.code.lstrip("0"), line.code)
        prev = merged.get(line.code)
        if prev is None:
            merged[line.code] = line
        else:
            prev.qty += line.qty
            prev.revenue = None if prev.revenue is None or line.revenue is None else prev.revenue + line.revenue
    report.lines = list(merged.values())


def _who(user: User) -> str:
    return (user.full_name or user.username)[:100]


def upload(db: Session, user: User, import_id: uuid.UUID, sales_date: date, file_name: str, data: bytes,
           prepared_by: str | None = None) -> SalesImport:
    report = parse(data)  # ParseError -> 422 in the API
    _match_known_codes(db, report)
    chash = content_hash(report)
    fhash = hashlib.sha256(data).hexdigest()

    existing = db.get(SalesImport, import_id)
    if existing is not None:  # a retried upload
        if existing.content_sha256 == chash and existing.sales_date == sales_date:
            return existing
        raise error(409, "A different sales import with this id already exists", "id_conflict")

    today = current_business_day(db)
    if sales_date > today:
        raise error(422, "The sales date is in the future", "future_date")
    if sales_date < today - timedelta(days=MAX_AGE_DAYS):
        raise error(422, "The sales date is more than a year in the past", "date_too_old")

    same_day = _active(db, SalesImport.sales_date == sales_date)
    if same_day is not None:
        if same_day.status != SalesImportStatus.draft:
            raise error(409, f"Sales for {sales_date.isoformat()} are already {same_day.status.value}", "already_posted",
                        import_id=str(same_day.id), status=same_day.status.value)
        db.delete(same_day)  # an unposted draft of the same day is replaced by the new upload
        db.flush()
    same_content = _active(db, SalesImport.content_sha256 == chash)
    if same_content is not None:
        raise error(409, f"These sales were already imported for {same_content.sales_date.isoformat()}", "same_file",
                    import_id=str(same_content.id), sales_date=same_content.sales_date.isoformat())

    # Remember every POS item; the name follows the latest report. Sorted: concurrent uploads lock in one order.
    db.execute(
        pg_insert(PosItem)
        .values(sorted(({"code": line.code, "name": line.name} for line in report.lines), key=lambda r: r["code"]))
        .on_conflict_do_update(index_elements=[PosItem.code], set_={"name": pg_insert(PosItem).excluded.name})
    )
    warnings = list(report.warnings)
    if (w := file_date_warning(report, sales_date)) is not None:
        warnings.append(w)
    imp = SalesImport(
        id=import_id,
        sales_date=sales_date,
        file_name=file_name[:255],
        file_sha256=fhash,
        content_sha256=chash,
        status=SalesImportStatus.draft,
        total_qty=report.total_qty,
        total_revenue=report.total_revenue,
        warnings=warnings,
        uploaded_by=user.id,
        prepared_by=(prepared_by or "").strip()[:100] or _who(user),
    )
    imp.lines = [
        SalesImportLine(line_no=i, pos_code=line.code, pos_name=line.name, qty=line.qty, revenue=line.revenue)
        for i, line in enumerate(report.lines, 1)
    ]
    db.add(imp)
    db.flush()
    return imp


def _lock(db: Session, import_id: uuid.UUID) -> SalesImport:
    imp = db.scalar(
        select(SalesImport).where(SalesImport.id == import_id).with_for_update().execution_options(populate_existing=True)
    )
    if imp is None:
        raise error(404, "Sales import not found", "not_found")
    return imp


def _check_location(db: Session, location_id: int) -> None:
    loc = db.get(Location, location_id)
    if loc is None or not loc.is_active:
        raise error(422, "Unknown or inactive location", "inactive_location", location_ids=[location_id])


def covered_pairs(db: Session, moment: datetime, location_id: int, product_ids) -> dict[int, tuple[int, datetime]]:
    """Products whose stock at the location a COMPLETED inventory counted at or after `moment`: that count already
    reflects these sales, so writing them off would count them twice (reply 32 P3; decided per product, reply 39 P2).
    Returns product_id -> (inventory_id, counted_at) of the first such count."""
    rows = db.execute(
        select(InventoryLine.product_id, Inventory.id, InventoryLine.counted_at)
        .join(Inventory, Inventory.id == InventoryLine.inventory_id)
        .where(
            Inventory.status == InventoryStatus.completed,
            Inventory.location_id == location_id,
            InventoryLine.counted_base.is_not(None),
            InventoryLine.counted_at >= moment,
            InventoryLine.product_id.in_(sorted(set(product_ids))),
        )
        .order_by(InventoryLine.product_id, InventoryLine.counted_at)
    ).all()
    out: dict[int, tuple[int, datetime]] = {}
    for pid, inv_id, at in rows:
        out.setdefault(pid, (inv_id, at))
    return out


# ---------------------------------------------------------------------- post
def post(db: Session, user: User, import_id: uuid.UUID, body: PostIn) -> SalesImport:
    """Write off the usage. Products already counted by a completed inventory after the sales are skipped and
    marked as covered; the rest is one write-off document. Nothing left -> status 'covered', no document."""
    imp = _lock(db, import_id)  # two clicks: the second waits here and then sees the first one's result
    if imp.status in DONE and imp.post_request_id == body.document_id:
        return imp  # retry of the same request
    if imp.status != SalesImportStatus.draft:
        raise error(409, f"This report is already {imp.status.value}", "not_draft", status=imp.status.value)
    _check_location(db, body.location_id)
    if db.get(StockDocument, body.document_id) is not None:
        raise error(409, "A different document with this id already exists", "id_conflict")

    usage = compute_usage(db, imp)
    if usage.unmapped and not body.acknowledge_unmapped:
        raise error(422, "Some sold items have no norm; set their norms or confirm writing off without them", "unmapped_items",
                    items=[{"code": line.pos_code, "name": line.pos_name, "qty": str(line.qty)} for line in usage.unmapped])
    totals = usage.totals()
    if not totals:
        raise error(422, "Nothing to write off: no sold item has a norm", "nothing_to_write_off")
    # Quantities corrected in the report: the difference is kept as a "manual correction" part of the breakdown.
    priced = any(x.unit_price is not None for x in body.lines)
    if priced and not has_perm(user.role, Perm.manage_catalog):  # prices are an admin function (reply 41, P1)
        raise error(403, "Only an administrator can change the cost of a write-off", "price_not_allowed")
    rate = posting.usd_rate(db) if body.price_currency == "USD" and priced else None
    price_in: dict[int, Decimal] = {}
    for x in body.lines:
        if x.product_id not in totals:
            raise error(422, "A corrected product is not part of this report", "unknown_product", product_ids=[x.product_id])
        delta = (x.qty_base - totals[x.product_id]).quantize(QTY_QUANT)
        if delta != 0:
            usage.parts.append(Part("", "Manual correction", Decimal(0), x.product_id, Decimal(0), delta))
        if x.unit_price is not None:
            price_in[x.product_id] = posting.to_won(x.unit_price, rate)
    totals = usage.totals()
    if not totals:
        raise error(422, "Nothing to write off: every quantity is zero", "nothing_to_write_off")

    moment = day_start(db, imp.sales_date)
    # Same lock order as every posting (products FOR SHARE, then balances), so the coverage decided here cannot
    # change before the write-off: completing an inventory needs these balance locks too.
    products = posting._lock_products(db, totals)
    posting._lock_balances(db, [(pid, body.location_id) for pid in totals])
    covered = covered_pairs(db, moment, body.location_id, totals)
    remaining = {pid: qty for pid, qty in totals.items() if pid not in covered}
    costs = {pid: (price_in[pid] / products[pid].unit_size).quantize(posting.COST_QUANT) if pid in price_in else posting.current_cost(products[pid])
             for pid in totals}

    doc = None
    if remaining:
        wo = WriteOffIn(
            id=body.document_id,
            doc_date=moment,
            comment=f"POS sales {imp.sales_date.isoformat()}" + (f", file {imp.file_name}" if imp.file_name else ""),
            reason=WriteOffReason.sales,
            allow_negative=body.allow_negative,
            lines=[
                WriteOffLineIn(product_id=pid, qty=qty, qty_unit=Unit(products[pid].base_unit.value), location_id=body.location_id)
                for pid, qty in sorted(remaining.items())
            ],
        )
        # The remaining pairs are not covered (checked above under the same locks), which is exactly what the
        # usual backdate check looks for: nothing more to check.
        doc = posting.post_write_off(db, user, wo, posting.request_hash("sales_write_off", wo), pre_check=lambda _pairs: None,
                                     cost_overrides={pid: costs[pid] for pid in remaining})

    for p in usage.parts:
        p.unit_cost_base = costs.get(p.product_id)
        if p.product_id in covered:
            p.covered_inventory_id, p.covered_at = covered[p.product_id]
    imp.status = SalesImportStatus.posted if doc else SalesImportStatus.covered
    imp.write_off_id = doc.id if doc else None
    imp.covered_inventory_id = min((c[0] for c in covered.values()), default=None)
    imp.location_id = body.location_id
    imp.post_request_id = body.document_id
    if body.prepared_by is not None:
        imp.prepared_by = body.prepared_by or None
    imp.closed_by, imp.closed_at = user.id, posting.db_now(db)
    _snapshot(imp, usage)
    db.flush()
    return imp


def _written_off(db: Session, imp: SalesImport) -> dict[int, Decimal]:
    if imp.write_off_id is None:
        return {}
    rows = db.execute(select(StockDocumentLine.product_id, StockDocumentLine.qty_base).where(StockDocumentLine.document_id == imp.write_off_id))
    return {pid: Decimal(q) for pid, q in rows}


def _rewrite(db: Session, user: User, imp: SalesImport, old: dict[int, Decimal], target: dict[int, Decimal],
             price_in: dict[int, Decimal], old_cost: dict[int, Decimal], reversal_id: uuid.UUID, document_id: uuid.UUID | None,
             allow_negative: bool, comment: str):
    """Replace the day's write-off `old` by `target` (empty: void) in one transaction (replies 48 and 50):
    1. reverse the old write-off (the absorption check is skipped: counted pairs are compensated in step 2);
    2. compensate every product an inventory counted after the sales by (target - old) at the earliest affected
       count, so each count still sees exactly what it saw and the stock after it stays as counted;
    3. post the new write-off at the start of the day (none for a void).
    Shared by correct() and void() so they cannot drift apart. Returns (new write-off or None, covered, costs)."""
    moment = day_start(db, imp.sales_date)
    loc = imp.location_id
    involved = set(target) | set(old)
    # lock order as everywhere: products FOR SHARE, then balances; coverage is decided under these locks
    products = posting._lock_products_any(db, involved) if not target else posting._lock_products(db, involved)
    posting._lock_balances(db, [(pid, loc) for pid in involved])
    covered = covered_pairs(db, moment, loc, involved)
    costs = {
        pid: (price_in[pid] / products[pid].unit_size).quantize(posting.COST_QUANT) if pid in price_in
        else old_cost[pid] if pid in old_cost else posting.current_cost(products[pid])
        for pid in involved
    }
    comp = {pid: (target.get(pid, Decimal(0)) - old.get(pid, Decimal(0))).quantize(QTY_QUANT) for pid in involved if pid in covered}
    comp = {pid: d for pid, d in comp.items() if d != 0}

    rev = ReverseIn(id=reversal_id, comment=comment)
    posting.reverse(db, user, imp.write_off_id, rev, posting.request_hash("reversal", ReverseKey(original=imp.write_off_id, body=rev)),
                    check_absorbed=False, from_sales_report=True)
    if comp:  # before the new write-off, so the running balance never dips falsely
        at = min(covered[pid][1] for pid in comp)
        inv_ids = sorted({covered[pid][0] for pid in comp})
        doc = StockDocument(
            id=uuid.uuid5(document_id or reversal_id, "compensation"),
            type=DocType.inventory_adjustment,
            doc_date=at,
            comment=f"{comment} after inventory " + ", ".join(f"#{i}" for i in inv_ids) + ": the counted stock stays as counted",
            created_by=user.id,
            allow_negative=False,
            sales_import_id=imp.id,
        )
        doc.lines = [
            StockDocumentLine(line_no=i, product_id=pid, location_from_id=None if d > 0 else loc, location_to_id=loc if d > 0 else None,
                              qty_base=d, unit_cost_base=costs[pid])
            for i, (pid, d) in enumerate(sorted(comp.items()), 1)
        ]
        posting._post(db, user, doc, [posting.Delta(pid, loc, d, costs[pid]) for pid, d in sorted(comp.items())], check_negative=False)
    new = None
    if target:
        wo = WriteOffIn(
            id=document_id,
            doc_date=moment,
            comment=f"POS sales {imp.sales_date.isoformat()} (corrected)" + (f", file {imp.file_name}" if imp.file_name else ""),
            reason=WriteOffReason.sales,
            allow_negative=allow_negative,
            lines=[
                WriteOffLineIn(product_id=pid, qty=qty, qty_unit=Unit(products[pid].base_unit.value), location_id=loc)
                for pid, qty in sorted(target.items())
            ],
        )
        new = posting.post_write_off(db, user, wo, posting.request_hash("sales_write_off", wo), pre_check=lambda _pairs: None,
                                     cost_overrides={pid: costs[pid] for pid in target})
    return new, covered, costs


def correct(db: Session, user: User, import_id: uuid.UUID, body: CorrectIn) -> SalesImport:
    """Edit a written-off report in place: its write-off is reversed and a new one posted with the corrected
    quantities and prices, on the same date and location (owner, 2026-11-25).

    A product that an inventory counted after the sales can be corrected too (owner, reply 48): the count is the
    truth about the stock at that moment, so the stock after it must not change. The difference d = new - old of
    such a product is written off at the start of the day as usual and returned by a compensating adjustment dated
    at the count (the earliest affected count, which is not later than any of them): the stock changes only
    between the sales and the count, and the count's shortage shrinks by d.
    """
    imp = _lock(db, import_id)
    if imp.status == SalesImportStatus.posted and imp.post_request_id == body.document_id:
        return imp  # retry of the same request
    if imp.status != SalesImportStatus.posted:
        raise error(409, f"Only a written-off report can be corrected (this one is {imp.status.value})", "not_posted",
                    status=imp.status.value)
    if db.get(StockDocument, body.document_id) is not None:
        raise error(409, "A different document with this id already exists", "id_conflict")
    if body.prepared_by is not None:
        imp.prepared_by = body.prepared_by or None
    if not body.lines:
        db.flush()
        return imp  # only the signature changed: no reversal for that

    usage = compute_usage(db, imp)  # the frozen snapshot, earlier corrections and costs included
    current = usage.totals()
    pids = {p.product_id for p in usage.parts}
    old_cost = {p.product_id: p.unit_cost_base for p in usage.parts if p.unit_cost_base is not None}
    old = _written_off(db, imp)
    target = dict(old)  # what the new write-off holds: as before, except the corrected products
    priced = any(x.unit_price is not None for x in body.lines)
    rate = posting.usd_rate(db) if body.price_currency == "USD" and priced else None
    price_in: dict[int, Decimal] = {}
    for x in body.lines:
        if x.product_id not in pids:
            raise error(422, "A corrected product is not part of this report", "unknown_product", product_ids=[x.product_id])
        delta = (x.qty_base - current.get(x.product_id, Decimal(0))).quantize(QTY_QUANT)
        if delta != 0:
            usage.parts.append(Part("", "Manual correction", Decimal(0), x.product_id, Decimal(0), delta))
        target[x.product_id] = x.qty_base.quantize(QTY_QUANT)
        if x.unit_price is not None:
            price_in[x.product_id] = posting.to_won(x.unit_price, rate)
    target = {pid: q for pid, q in target.items() if q > 0}
    if not target:
        raise error(422, "Nothing would be written off; to cancel the whole day use Void", "nothing_to_write_off")

    new, covered, costs = _rewrite(db, user, imp, old, target, price_in, old_cost, body.reversal_id, body.document_id,
                                   body.allow_negative, f"Correction of POS sales {imp.sales_date.isoformat()}")
    for p in usage.parts:
        if p.product_id in target:
            p.unit_cost_base = costs[p.product_id]
        if p.product_id in covered:
            p.covered_inventory_id, p.covered_at = covered[p.product_id]
    imp.write_off_id = new.id
    imp.post_request_id = body.document_id
    imp.closed_by, imp.closed_at = user.id, posting.db_now(db)
    _snapshot(imp, usage)
    db.flush()
    return imp


def set_prepared_by(db: Session, user: User, import_id: uuid.UUID, prepared_by: str | None) -> SalesImport:
    """Sign a report without touching the stock: drafts by whoever may post, closed reports by an admin."""
    imp = _lock(db, import_id)
    if imp.status != SalesImportStatus.draft and not has_perm(user.role, Perm.reverse_document):
        raise error(403, "Only an administrator can change the signature of a closed report", "forbidden")
    imp.prepared_by = prepared_by or None
    db.flush()
    return imp


def void(db: Session, user: User, import_id: uuid.UUID, body: VoidIn) -> SalesImport:
    """Cancel the day. A written-off day is rewritten to nothing: its write-off is reversed and the products an
    inventory counted after the sales are compensated, so the counts stay true (reply 50)."""
    imp = _lock(db, import_id)
    if imp.status == SalesImportStatus.voided:
        return imp
    if imp.status == SalesImportStatus.posted:
        usage = compute_usage(db, imp)
        old_cost = {p.product_id: p.unit_cost_base for p in usage.parts if p.unit_cost_base is not None}
        _rewrite(db, user, imp, _written_off(db, imp), {}, {}, old_cost, body.reversal_id, None, False,
                 f"Void of POS sales {imp.sales_date.isoformat()}")
    imp.status = SalesImportStatus.voided
    imp.closed_by, imp.closed_at = user.id, posting.db_now(db)
    db.flush()
    return imp


def discard(db: Session, import_id: uuid.UUID) -> None:
    imp = _lock(db, import_id)
    if imp.status != SalesImportStatus.draft:
        raise error(409, "Only an unposted report can be deleted", "not_draft", status=imp.status.value)
    db.execute(delete(SalesImport).where(SalesImport.id == imp.id))
    db.flush()


# -------------------------------------------------------------- pending days
def pending_days(db: Session, location_id: int) -> tuple[date | None, list[date], int]:
    """Business days since the last report written off (or covered) at this location that have no such report.

    Shown before completing an inventory: sales of those days are still in the expected quantity, so the count
    would show them as a shortage (reply 32, P3). Locations that never had a POS write-off get no warning."""
    last = db.scalar(select(func.max(SalesImport.sales_date)).where(SalesImport.location_id == location_id, SalesImport.status.in_(DONE)))
    if last is None:
        return None, [], 0
    today = current_business_day(db)
    done = set(db.scalars(select(SalesImport.sales_date).where(SalesImport.status.in_(DONE), SalesImport.sales_date > last)))
    days = [last + timedelta(days=i) for i in range(1, (today - last).days + 1)]
    days = [d for d in days if d not in done]
    return last, days[:PENDING_LIMIT], max(0, len(days) - PENDING_LIMIT)
