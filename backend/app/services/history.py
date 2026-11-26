"""Stock of one product by business day, for the chart on the product card (owner, reply 98: "a chart of the
stock of every item, by day").

Each point is the balance at the END of a business day (the installation's time zone, the day starts at
`business_day_starts_at`), by `doc_date`: a backdated document lands in its own day. Days without movements carry
the previous balance; the first point starts from the balance before the period.
`qty_in` / `qty_out` are what came in and went out that day over all places: each document's net change of this
product, so a transfer between two places (net 0) is neither.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models import Location, StockMovement
from app.services import sales

PERIODS = (7, 30, 90)


def check_period(days: int) -> None:
    if days not in PERIODS:
        raise HTTPException(422, {"code": "bad_period", "message": "days must be 7, 30 or 90"})


def history(db: Session, product_id: int, days: int) -> dict:
    tz, start = sales._day_settings(db)
    today = sales.current_business_day(db)
    first = today - timedelta(days=days - 1)
    lo = sales.day_start(db, first)
    shift = timedelta(hours=start.hour, minutes=start.minute)
    # local wall time minus the day's start hour, then the date: 05:59 KST belongs to the day before
    bday = cast(func.timezone(tz.key, StockMovement.doc_date) - shift, Date).label("bday")
    mine = StockMovement.product_id == product_id

    opening: dict[int, Decimal] = dict(db.execute(
        select(StockMovement.location_id, func.sum(StockMovement.delta_base)).where(mine, StockMovement.doc_date < lo)
        .group_by(StockMovement.location_id)).all())
    by_place: dict[tuple[int, date], Decimal] = {}
    for loc, d, qty in db.execute(
        select(StockMovement.location_id, bday, func.sum(StockMovement.delta_base)).where(mine, StockMovement.doc_date >= lo)
        .group_by(StockMovement.location_id, bday)
    ):
        key = (loc, min(d, today))  # a document up to 5 minutes ahead of the clock still belongs to today
        by_place[key] = by_place.get(key, Decimal(0)) + qty
    flows: dict[date, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for d, net in db.execute(
        select(bday, func.sum(StockMovement.delta_base)).where(mine, StockMovement.doc_date >= lo)
        .group_by(bday, StockMovement.document_id)
    ):
        if net > 0:
            flows[min(d, today)][0] += net
        elif net < 0:
            flows[min(d, today)][1] -= net

    places = sorted({loc for loc, q in opening.items() if q != 0} | {loc for loc, _ in by_place})
    names = dict(db.execute(select(Location.id, Location.name).where(Location.id.in_(places))).all()) if places else {}
    running = {loc: Decimal(opening.get(loc, 0)) for loc in places}
    points, per_place = [], {loc: [] for loc in places}
    for i in range(days):
        d = first + timedelta(days=i)
        for loc in places:
            running[loc] += by_place.get((loc, d), Decimal(0))
            per_place[loc].append(running[loc])
        qty_in, qty_out = flows.get(d, (Decimal(0), Decimal(0)))
        points.append({"day": d, "balance": sum(running.values(), Decimal(0)), "qty_in": qty_in, "qty_out": qty_out})
    return {
        "days": days,
        "points": points,
        "places": sorted(({"location_id": loc, "location_name": names.get(loc, ""), "balances": per_place[loc]} for loc in places),
                         key=lambda x: x["location_name"].lower()),
    }
