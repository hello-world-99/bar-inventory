"""Usage over a period ("Used" column of Stock and Products; owner, reply 77: "a column with what was spent").

Quantities only:
  * used  — write-offs of every reason (POS sales included), net of their reversals;
  * count — the net result of inventory counts (adjustments, POS compensations included): positive = shortage.
Transfers and receipts are not usage. The period is whole business days in the installation's time zone, the same
days as the POS reports: `days=1` is today's business day, `days=7` today and the six before it.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, aliased

from app.models import DocType, StockDocument, StockMovement
from app.services import sales

PERIODS = (1, 7, 30)


def check_period(days: int | None) -> None:
    if days is not None and days not in PERIODS:
        raise HTTPException(422, {"code": "bad_period", "message": "used_days must be 1, 7 or 30"})


def period_start(db: Session, days: int):
    return sales.day_start(db, sales.current_business_day(db) - timedelta(days=days - 1))


def usage(db: Session, days: int, *, by_location: bool) -> dict[tuple, tuple[Decimal, Decimal]]:
    """{(product_id,) or (product_id, location_id): (used, count_loss)} for the last `days` business days."""
    orig = aliased(StockDocument)
    kind = case(
        (StockDocument.type == DocType.write_off, "use"),
        (and_(StockDocument.type == DocType.reversal, orig.type == DocType.write_off), "use"),
        (StockDocument.type == DocType.inventory_adjustment, "count"),
        else_=None,
    ).label("kind")
    keys = [StockMovement.product_id] + ([StockMovement.location_id] if by_location else [])
    rows = db.execute(
        select(*keys, kind, func.sum(StockMovement.delta_base))
        .join(StockDocument, StockDocument.id == StockMovement.document_id)
        .outerjoin(orig, orig.id == StockDocument.reversal_of)
        .where(StockMovement.doc_date >= period_start(db, days), kind.is_not(None))
        .group_by(*keys, kind)
    ).all()
    out: dict[tuple, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for *key, k, total in rows:
        out[tuple(key)][0 if k == "use" else 1] -= Decimal(total)  # movements are negative when stock leaves
    return {k: (v[0], v[1]) for k, v in out.items()}
