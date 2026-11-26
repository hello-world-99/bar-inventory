"""Stock by business day for the product chart (reply 98)."""

import uuid
from datetime import timedelta
from decimal import Decimal

from app.services import sales
from tests.test_posting import receipt, world, write_off  # noqa: F401  (fixture)

P = "/api/v1"


def iso(dt):
    return dt.isoformat()


def test_history_by_business_day(client, db, admin_h, staff_h, world):
    today = sales.current_business_day(db)
    start = lambda d: sales.day_start(db, d)  # noqa: E731
    receipt(client, admin_h, world, qty="10", doc_date=iso(start(today - timedelta(days=3)) + timedelta(hours=1)))
    # 05:30 local, before the 06:00 day start: belongs to the business day before
    receipt(client, admin_h, world, qty="1", doc_date=iso(start(today - timedelta(days=1)) - timedelta(minutes=30)))
    write_off(client, admin_h, world, "2", doc_date=iso(start(today - timedelta(days=1)) + timedelta(hours=2)))
    t = {"id": str(uuid.uuid4()), "from_location_id": world["main"], "to_location_id": world["bar"],
         "lines": [{"product_id": world["vodka"], "qty": "3"}]}
    assert client.post(f"{P}/transfers", json=t, headers=admin_h).status_code == 201
    write_off(client, admin_h, world, "1", location="bar")

    r = client.get(f"{P}/products/{world['vodka']}/history", params={"days": 7}, headers=staff_h)
    assert r.status_code == 200, r.text
    h = r.json()
    pts = h["points"]
    assert len(pts) == 7 and pts[-1]["day"] == today.isoformat() and pts[0]["day"] == (today - timedelta(days=6)).isoformat()
    bal = [Decimal(p["balance"]) for p in pts]
    assert bal == [0, 0, 0, 7000, 7700, 6300, 5600]
    assert (Decimal(pts[3]["qty_in"]), Decimal(pts[4]["qty_in"]), Decimal(pts[5]["qty_out"])) == (7000, 700, 1400)
    assert Decimal(pts[6]["qty_in"]) == 0 and Decimal(pts[6]["qty_out"]) == 700  # the transfer is neither in nor out
    places = {p["location_name"]: [Decimal(x) for x in p["balances"]] for p in h["places"]}
    assert places["Main"][-1] == 4200 and places["Bar"][-1] == 1400 and places["Bar"][-2] == 0
    # the last point is today's stock
    stock = sum(Decimal(r["qty_base"]) for r in client.get(f"{P}/stock", headers=staff_h).json() if r["product_id"] == world["vodka"])
    assert bal[-1] == stock

    # a longer window has the same days at its end
    long = client.get(f"{P}/products/{world['vodka']}/history", params={"days": 30}, headers=staff_h).json()
    assert len(long["points"]) == 30 and [Decimal(p["balance"]) for p in long["points"][-7:]] == bal
    assert client.get(f"{P}/products/{world['vodka']}/history", params={"days": 5}, headers=staff_h).status_code == 422
    assert client.get(f"{P}/products/999999/history", headers=staff_h).status_code == 404
