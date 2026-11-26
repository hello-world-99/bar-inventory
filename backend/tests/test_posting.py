"""Posting service: receipts, write-offs, transfers, reversals, journal, idempotency, invariants."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.conftest import auth_headers

P = "/api/v1"


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def world(client, admin_h):
    def cat(code):
        return next(c["id"] for c in client.get(f"{P}/categories", headers=admin_h).json() if c["code"] == code)

    def loc(name):
        return client.post(f"{P}/locations", json={"name": name}, headers=admin_h).json()["id"]

    def prod(**kw):
        r = client.post(f"{P}/products", json=kw, headers=admin_h)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return {
        "main": loc("Main"),
        "bar": loc("Bar"),
        "vodka": prod(name="Vodka", sku="V", category_id=cat("alcohol"), unit="bottle", unit_size="700", purchase_price="14.00"),
        "lime": prod(name="Lime", sku="L", category_id=cat("food_ingredients"), unit="kg", purchase_price="4.00"),
    }


def balance(db, product, location) -> Decimal:
    v = db.execute(text("SELECT qty_base FROM stock_balances WHERE product_id=:p AND location_id=:l"), {"p": product, "l": location}).scalar()
    return Decimal(v) if v is not None else Decimal(0)


def assert_journal_consistent(db):
    bad = db.execute(text(
        "SELECT b.product_id, b.location_id FROM stock_balances b "
        "LEFT JOIN (SELECT product_id, location_id, sum(delta_base) s FROM stock_movements GROUP BY 1,2) m "
        "USING (product_id, location_id) WHERE b.qty_base <> coalesce(m.s, 0)"
    )).all()
    assert bad == []


def receipt(client, h, w, qty="10", price="14.00", product="vodka", location="main", **kw):
    body = {"id": str(uuid.uuid4()), "lines": [{"product_id": w[product], "location_id": w[location], "qty": qty, "unit_price": price}]} | kw
    return client.post(f"{P}/receipts", json=body, headers=h)


def write_off(client, h, w, qty, product="vodka", location="main", **kw):
    body = {"id": str(uuid.uuid4()), "reason": "breakage", "lines": [{"product_id": w[product], "location_id": w[location], "qty": qty} | kw.pop("line", {})]} | kw
    return client.post(f"{P}/write-offs", json=body, headers=h)


def complete_inventory(db, user_id, location, product, at=None):
    """Insert a completed inventory that counted `product` at `location` (stage 4 will create these via the API)."""
    inv = db.execute(text(
        "INSERT INTO inventories (location_id, status, started_by, started_at, completed_by, completed_at) "
        "VALUES (:l, 'completed', :u, coalesce(:at, now()), :u, coalesce(:at, now())) RETURNING id"
    ), {"l": location, "u": user_id, "at": at}).scalar()
    db.execute(text(
        "INSERT INTO inventory_lines (inventory_id, product_id, expected_at_start_base, counted_base, expected_at_count_base, counted_at, counted_by) "
        "VALUES (:i, :p, 0, 0, 0, coalesce(:at, now()), :u)"
    ), {"i": inv, "p": product, "u": user_id, "at": at})
    db.commit()


# ------------------------------------------------------------------ receipts
def test_receipt_increases_stock_and_records_cost(client, db, admin_h, world):
    r = receipt(client, admin_h, world, qty="2", price="15.40", supplier="Wine & Co", invoice_no="A-1")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["type"] == "receipt" and d["status"] == "posted" and d["supplier"] == "Wine & Co"
    line = d["lines"][0]
    assert Decimal(line["qty_base"]) == 1400
    assert Decimal(line["unit_price"]) == Decimal("15.40")  # exactly as entered
    assert Decimal(line["unit_cost_base"]) == Decimal("0.022000")
    assert balance(db, world["vodka"], world["main"]) == 1400
    # latest price becomes the product's purchase price
    p = client.get(f"{P}/products/{world['vodka']}", headers=admin_h).json()
    assert Decimal(p["purchase_price"]) == Decimal("15.40")
    assert_journal_consistent(db)


def test_receipt_quantity_in_other_units(client, db, admin_h, world):
    body = {"id": str(uuid.uuid4()), "lines": [
        {"product_id": world["lime"], "location_id": world["main"], "qty": "1500", "qty_unit": "g", "unit_price": "4.00"},
        {"product_id": world["vodka"], "location_id": world["main"], "qty": "1.4", "qty_unit": "l", "unit_price": "14.00"},
    ]}
    assert client.post(f"{P}/receipts", json=body, headers=admin_h).status_code == 201
    assert balance(db, world["lime"], world["main"]) == 1500
    assert balance(db, world["vodka"], world["main"]) == 1400
    bad = {"id": str(uuid.uuid4()), "lines": [{"product_id": world["lime"], "location_id": world["main"], "qty": "1", "qty_unit": "bottle", "unit_price": "1"}]}
    r = client.post(f"{P}/receipts", json=bad, headers=admin_h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_unit"


def test_backdated_receipt_does_not_override_newer_price(client, admin_h, world):
    assert receipt(client, admin_h, world, price="16.00").status_code == 201
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    assert receipt(client, admin_h, world, price="12.00", doc_date=old).status_code == 201
    p = client.get(f"{P}/products/{world['vodka']}", headers=admin_h).json()
    assert Decimal(p["purchase_price"]) == Decimal("16.00")


def test_future_and_naive_dates_rejected(client, admin_h, world):
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = receipt(client, admin_h, world, doc_date=future)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "future_date"
    assert receipt(client, admin_h, world, doc_date="2026-01-01T10:00:00").status_code == 422


def test_inactive_product_or_location_rejected(client, admin_h, world):
    client.patch(f"{P}/locations/{world['bar']}", json={"is_active": False}, headers=admin_h)
    assert receipt(client, admin_h, world, location="bar").json()["detail"]["code"] == "inactive_location"
    client.patch(f"{P}/products/{world['lime']}", json={"is_active": False}, headers=admin_h)
    assert receipt(client, admin_h, world, product="lime").json()["detail"]["code"] == "inactive_product"


# ----------------------------------------------------------------- write-offs
def test_write_off_partial_bottle_in_ml(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="1")
    r = write_off(client, staff_h, world, "50", line={"qty_unit": "ml"}, reason="staff_use", comment="tasting")
    assert r.status_code == 201, r.text
    assert r.json()["reason"] == "staff_use"
    assert balance(db, world["vodka"], world["main"]) == 650
    assert Decimal(r.json()["lines"][0]["unit_cost_base"]) == Decimal("0.020000")  # 14.00 / 700


def test_write_off_requires_reason(client, admin_h, world):
    body = {"id": str(uuid.uuid4()), "lines": [{"product_id": world["vodka"], "location_id": world["main"], "qty": "1"}]}
    assert client.post(f"{P}/write-offs", json=body, headers=admin_h).status_code == 422


def test_stock_never_goes_negative(client, db, admin_h, staff_h, world):
    """Owner (reply 96): no negative balance for anyone, the old override flag is ignored."""
    receipt(client, admin_h, world, qty="1")
    for h in (staff_h, admin_h):
        for flag in (False, True):
            r = write_off(client, h, world, "2", allow_negative=flag)
            assert r.status_code == 422, r.text
            d = r.json()["detail"]
            assert d["code"] == "insufficient_stock" and d["can_override"] is False
            assert "Vodka" in d["message"] and "700 ml in stock" in d["message"] and "1400 ml needed" in d["message"]
            assert d["items"][0]["available"] == "700.000" and d["items"][0]["requested"] == "1400.000"
    assert write_off(client, staff_h, world, "1").status_code == 201  # down to exactly zero is fine
    assert balance(db, world["vodka"], world["main"]) == 0
    assert db.execute(text("SELECT count(*) FROM stock_balances WHERE qty_base < 0")).scalar() == 0
    assert_journal_consistent(db)


def test_allow_negative_flag_only_recorded_when_used(client, admin_h, world):
    receipt(client, admin_h, world, qty="5")
    r = write_off(client, admin_h, world, "1", allow_negative=True)
    assert r.status_code == 201 and r.json()["allow_negative"] is False


# ------------------------------------------------------------------ transfers
def test_transfer_moves_stock_between_locations(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="3")
    body = {"id": str(uuid.uuid4()), "from_location_id": world["main"], "to_location_id": world["bar"],
            "lines": [{"product_id": world["vodka"], "qty": "1.5"}]}
    r = client.post(f"{P}/transfers", json=body, headers=staff_h)
    assert r.status_code == 201, r.text
    assert balance(db, world["vodka"], world["main"]) == 1050
    assert balance(db, world["vodka"], world["bar"]) == 1050
    # total across locations is unchanged
    assert Decimal(client.get(f"{P}/products/{world['vodka']}", headers=admin_h).json()["total_qty_base"]) == 2100
    same = body | {"id": str(uuid.uuid4()), "to_location_id": world["main"]}
    assert client.post(f"{P}/transfers", json=same, headers=admin_h).json()["detail"]["code"] == "same_location"
    too_much = body | {"id": str(uuid.uuid4()), "lines": [{"product_id": world["vodka"], "qty": "5"}]}
    assert client.post(f"{P}/transfers", json=too_much, headers=staff_h).status_code == 422
    assert_journal_consistent(db)


# ---------------------------------------------------------------- idempotency
def test_retry_with_same_id_returns_same_document(client, db, admin_h, world):
    body = {"id": str(uuid.uuid4()), "lines": [{"product_id": world["vodka"], "location_id": world["main"], "qty": "1", "unit_price": "14"}]}
    r1 = client.post(f"{P}/receipts", json=body, headers=admin_h)
    r2 = client.post(f"{P}/receipts", json=body, headers=admin_h)
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json()["id"] == r2.json()["id"]
    assert balance(db, world["vodka"], world["main"]) == 700
    changed = body | {"lines": [{"product_id": world["vodka"], "location_id": world["main"], "qty": "2", "unit_price": "14"}]}
    r3 = client.post(f"{P}/receipts", json=changed, headers=admin_h)
    assert r3.status_code == 409 and r3.json()["detail"]["code"] == "id_conflict"
    # same id on a different endpoint is a conflict as well
    wo = {"id": body["id"], "reason": "other", "lines": [{"product_id": world["vodka"], "location_id": world["main"], "qty": "1"}]}
    assert client.post(f"{P}/write-offs", json=wo, headers=admin_h).status_code == 409


# ------------------------------------------------------------------ reversals
def test_reverse_receipt_restores_balances(client, db, admin_h, staff_h, world):
    doc = receipt(client, admin_h, world, qty="7").json()
    rev_body = {"id": str(uuid.uuid4()), "comment": "typo: 70 instead of 7"}
    assert client.post(f"{P}/documents/{doc['id']}/reverse", json=rev_body, headers=staff_h).status_code == 403
    r = client.post(f"{P}/documents/{doc['id']}/reverse", json=rev_body, headers=admin_h)
    assert r.status_code == 201, r.text
    rev = r.json()
    assert rev["type"] == "reversal" and rev["reversal_of"] == doc["id"]
    assert balance(db, world["vodka"], world["main"]) == 0
    assert client.get(f"{P}/documents/{doc['id']}", headers=admin_h).json()["reversed_by"] == rev["id"]
    # retry is idempotent, a second reversal is refused
    assert client.post(f"{P}/documents/{doc['id']}/reverse", json=rev_body, headers=admin_h).status_code == 200
    again = client.post(f"{P}/documents/{doc['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_reversed"
    # reversals themselves are not reversible
    assert client.post(f"{P}/documents/{rev['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h).status_code == 422
    assert_journal_consistent(db)


def test_reverse_transfer_and_write_off(client, db, admin_h, world):
    receipt(client, admin_h, world, qty="2")
    t = client.post(f"{P}/transfers", json={"id": str(uuid.uuid4()), "from_location_id": world["main"], "to_location_id": world["bar"], "lines": [{"product_id": world["vodka"], "qty": "1"}]}, headers=admin_h).json()
    w = write_off(client, admin_h, world, "1", location="bar").json()
    assert client.post(f"{P}/documents/{w['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h).status_code == 201
    assert client.post(f"{P}/documents/{t['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h).status_code == 201
    assert balance(db, world["vodka"], world["main"]) == 1400
    assert balance(db, world["vodka"], world["bar"]) == 0
    assert_journal_consistent(db)


def test_reverse_receipt_after_stock_was_used_is_refused(client, db, admin_h, world):
    doc = receipt(client, admin_h, world, qty="1").json()
    write_off(client, admin_h, world, "1")
    for flag in (False, True):
        r = client.post(f"{P}/documents/{doc['id']}/reverse", json={"id": str(uuid.uuid4()), "allow_negative": flag}, headers=admin_h)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "insufficient_stock"
    assert balance(db, world["vodka"], world["main"]) == 0


def test_reverse_refused_after_inventory_counted_the_pair(client, db, admin, admin_h, world):
    """A1/B2: even when the count matched (delta 0, no adjustment movement) the document is already absorbed."""
    doc = receipt(client, admin_h, world, qty="10").json()
    complete_inventory(db, admin.id, world["main"], world["vodka"])
    r = client.post(f"{P}/documents/{doc['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "counted_after"


def test_reverse_allowed_when_inventory_did_not_count_the_product(client, db, admin, admin_h, world):
    doc = receipt(client, admin_h, world, qty="10").json()
    complete_inventory(db, admin.id, world["main"], world["lime"])  # different product
    assert client.post(f"{P}/documents/{doc['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h).status_code == 201


# ----------------------------------------------------------------- backdating
def test_backdate_before_last_inventory(client, db, admin, admin_h, staff_h, world):
    complete_inventory(db, admin.id, world["main"], world["vodka"])
    old = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    r = receipt(client, staff_h, world, doc_date=old)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "backdate_forbidden"
    r = receipt(client, admin_h, world, doc_date=old)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "backdate_confirmation_required"
    r = receipt(client, admin_h, world, doc_date=old, confirm_backdate=True)
    assert r.status_code == 201 and r.json()["backdate_confirmed"] is True
    # the check is per (product, location) pair that was counted: other locations and products are free
    assert receipt(client, staff_h, world, doc_date=old, location="bar").status_code == 201
    assert receipt(client, staff_h, world, doc_date=old, product="lime", price="4").status_code == 201


def test_document_dated_after_the_count_is_not_a_backdate(client, db, admin, admin_h, staff_h, world):
    """Counted yesterday, completed; a write-off dated this morning happened after the count -> allowed."""
    yesterday = datetime.now(UTC) - timedelta(days=1)
    complete_inventory(db, admin.id, world["main"], world["vodka"], at=yesterday)
    receipt(client, admin_h, world, qty="2")
    this_morning = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert write_off(client, staff_h, world, "1", doc_date=this_morning).status_code == 201


def test_date_bounds(client, admin_h, world):
    too_old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    r = receipt(client, admin_h, world, doc_date=too_old)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "date_too_old"


def test_huge_quantities_are_rejected_not_500(client, admin_h, world):
    """R1 from reply 15."""
    r = receipt(client, admin_h, world, qty="99999999999")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "qty_too_large"
    for _ in range(2):  # each line within limits, but the balance would overflow NUMERIC(14,3)
        receipt(client, admin_h, world, product="lime", qty="900000", price="1")  # 9e8 g each
    many = {"id": str(uuid.uuid4()), "lines": [{"product_id": world["lime"], "location_id": world["main"], "qty": "999999", "unit_price": "1"}] * 120}
    r = client.post(f"{P}/receipts", json=many, headers=admin_h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "qty_too_large"


def test_reversal_carries_original_date(client, admin_h, world):
    old = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0)
    doc = receipt(client, admin_h, world, doc_date=old.isoformat()).json()
    rev = client.post(f"{P}/documents/{doc['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h).json()
    assert datetime.fromisoformat(rev["doc_date"]) == old
    moves = client.get(f"{P}/journal", params={"type": "reversal"}, headers=admin_h).json()["items"]
    assert {datetime.fromisoformat(m["doc_date"]) for m in moves} == {old}


# -------------------------------------------------------------- immutability
def test_units_cannot_change_after_posting(client, admin_h, world):
    receipt(client, admin_h, world)
    assert client.patch(f"{P}/products/{world['vodka']}", json={"unit_size": "750"}, headers=admin_h).status_code == 409


# --------------------------------------------------------- journal and stock
def test_journal_filters_and_amounts(client, admin_h, world):
    receipt(client, admin_h, world, qty="2")
    receipt(client, admin_h, world, qty="1", product="lime", price="4.00")
    write_off(client, admin_h, world, "1")
    j = client.get(f"{P}/journal", headers=admin_h).json()
    assert j["total"] == 3
    only_wo = client.get(f"{P}/journal", params={"type": "write_off"}, headers=admin_h).json()
    assert only_wo["total"] == 1 and Decimal(only_wo["items"][0]["delta_base"]) == -700
    assert Decimal(only_wo["items"][0]["amount"]) == Decimal("-14.000000")
    assert client.get(f"{P}/journal", params={"product_id": world["lime"]}, headers=admin_h).json()["total"] == 1
    assert client.get(f"{P}/journal", params={"type": ["receipt", "write_off"], "product_id": world["vodka"]}, headers=admin_h).json()["total"] == 2
    today = datetime.now(UTC).date()
    assert client.get(f"{P}/journal", params={"date_from": str(today - timedelta(days=1)), "date_to": str(today + timedelta(days=1))}, headers=admin_h).json()["total"] == 3
    assert client.get(f"{P}/journal", params={"date_to": str(today - timedelta(days=5))}, headers=admin_h).json()["total"] == 0


def test_documents_list(client, admin_h, world):
    receipt(client, admin_h, world, qty="2", price="14.00")
    write_off(client, admin_h, world, "1")
    docs = client.get(f"{P}/documents", params={"type": "receipt"}, headers=admin_h).json()
    assert docs["total"] == 1 and docs["items"][0]["line_count"] == 1
    assert Decimal(docs["items"][0]["total_amount"]) == Decimal("28.000000")
    assert client.get(f"{P}/documents", params={"location_id": world["bar"]}, headers=admin_h).json()["total"] == 0


def test_stock_and_reconcile(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="1.5")
    rows = client.get(f"{P}/stock", params={"location_id": world["main"]}, headers=staff_h).json()
    assert len(rows) == 1 and Decimal(rows[0]["qty_base"]) == 1050 and Decimal(rows[0]["value"]) == 21
    assert client.get(f"{P}/stock/reconcile", headers=admin_h).json() == []
    assert client.get(f"{P}/stock/reconcile", headers=staff_h).status_code == 403


def test_receipt_without_prices(client, db, admin_h, world):
    """Owner, reply 59: no money in receipts. The cost is the product's price, which stays as it is."""
    body = {"id": str(uuid.uuid4()), "lines": [{"product_id": world["vodka"], "location_id": world["main"], "qty": "2"}]}
    r = client.post(f"{P}/receipts", json=body, headers=admin_h)
    assert r.status_code == 201, r.text
    line = r.json()["lines"][0]
    assert line["unit_price"] is None and Decimal(line["unit_cost_base"]) == Decimal("0.020000")  # 14.00 per 700 ml bottle
    assert balance(db, world["vodka"], world["main"]) == 1400
    p = client.get(f"{P}/products/{world['vodka']}", headers=admin_h).json()
    assert Decimal(p["purchase_price"]) == Decimal("14.00")
    # a retry is the same request (absent and null price hash the same)
    again = client.post(f"{P}/receipts", json=body | {"lines": [body["lines"][0] | {"unit_price": None}]}, headers=admin_h)
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    assert balance(db, world["vodka"], world["main"]) == 1400
    # a later priced receipt still updates the price
    receipt(client, admin_h, world, qty="1", price="15.00")
    assert Decimal(client.get(f"{P}/products/{world['vodka']}", headers=admin_h).json()["purchase_price"]) == Decimal("15.00")


def test_journal_shows_balance_and_minimum(client, admin_h, world):
    """Reply 72: the journal shows the balance after each movement and the product's minimum (for "running out")."""
    client.patch(f"{P}/products/{world['lime']}", json={"min_stock_base": "500"}, headers=admin_h)
    receipt(client, admin_h, world, qty="1", price="4", product="lime")
    write_off(client, admin_h, world, "0.7", product="lime")
    rows = client.get(f"{P}/journal", params={"product_id": world["lime"]}, headers=admin_h).json()["items"]
    assert [(Decimal(r["delta_base"]), Decimal(r["balance_after"]), Decimal(r["min_stock_base"])) for r in rows] == [
        (Decimal(-700), Decimal(300), Decimal(500)), (Decimal(1000), Decimal(1000), Decimal(500))]


def test_document_lines_show_the_balance_after(client, admin_h, world):
    """Reply 73: a document shows the balance right after each of its lines (history, not today's stock)."""
    receipt(client, admin_h, world, qty="3")
    r = client.post(f"{P}/transfers", json={"id": str(uuid.uuid4()), "from_location_id": world["main"], "to_location_id": world["bar"],
                                             "lines": [{"product_id": world["vodka"], "qty": "1"}]}, headers=admin_h)
    line = r.json()["lines"][0]
    assert (Decimal(line["balance_after_from"]), Decimal(line["balance_after_to"])) == (1400, 700)
    receipt(client, admin_h, world, qty="5")  # later documents do not change what this one shows
    again = client.get(f"{P}/documents/{r.json()['id']}", headers=admin_h).json()["lines"][0]
    assert Decimal(again["balance_after_from"]) == 1400


def test_used_column_counts_net_write_offs_only(client, db, admin_h, world):
    """Reply 77: "Used" = write-offs (any reason) net of reversals; transfers and receipts are not usage; counts apart."""
    receipt(client, admin_h, world, qty="10")
    write_off(client, admin_h, world, "2")                                                   # 1400 ml used
    w = write_off(client, admin_h, world, "1").json()                                        # 700 ml, then reversed
    client.post(f"{P}/documents/{w['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h)
    client.post(f"{P}/transfers", json={"id": str(uuid.uuid4()), "from_location_id": world["main"], "to_location_id": world["bar"],
                                         "lines": [{"product_id": world["vodka"], "qty": "3"}]}, headers=admin_h)
    rows = {r["location_id"]: r for r in client.get(f"{P}/stock", params={"used_days": 7}, headers=admin_h).json() if r["product_id"] == world["vodka"]}
    assert Decimal(rows[world["main"]]["used_base"]) == 1400 and Decimal(rows[world["bar"]]["used_base"]) == 0
    assert Decimal(rows[world["main"]]["count_loss_base"]) == 0
    prods = {p["id"]: p for p in client.get(f"{P}/products", params={"used_days": 1}, headers=admin_h).json()["items"]}
    assert Decimal(prods[world["vodka"]]["used_base"]) == 1400 and Decimal(prods[world["lime"]]["used_base"]) == 0
    assert client.get(f"{P}/stock", headers=admin_h).json()[0]["used_base"] is None  # only when asked for
    assert client.get(f"{P}/stock", params={"used_days": 5}, headers=admin_h).status_code == 422


def test_used_period_follows_the_business_day(client, db, admin_h, world):
    """The period starts at the business day start (06:00 in the installation's time zone)."""
    from datetime import datetime, timedelta, timezone
    receipt(client, admin_h, world, qty="10", doc_date=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat())
    # 2 days ago -> inside 7 days, outside today
    write_off(client, admin_h, world, "1", doc_date=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    prods = {p["id"]: p for p in client.get(f"{P}/products", params={"used_days": 1}, headers=admin_h).json()["items"]}
    assert Decimal(prods[world["vodka"]]["used_base"]) == 0
    prods = {p["id"]: p for p in client.get(f"{P}/products", params={"used_days": 7}, headers=admin_h).json()["items"]}
    assert Decimal(prods[world["vodka"]]["used_base"]) == 700


def test_count_shortage_is_reported_apart(client, db, admin, admin_h, world):
    receipt(client, admin_h, world, qty="10")
    inv = client.post(f"{P}/inventories", json={"location_id": world["main"]}, headers=admin_h).json()
    client.put(f"{P}/inventories/{inv['id']}/lines/{world['vodka']}", json={"parts": [{"qty": "9", "qty_unit": "bottle"}]}, headers=admin_h)
    client.post(f"{P}/inventories/{inv['id']}/complete", json={}, headers=admin_h)
    row = next(r for r in client.get(f"{P}/stock", params={"used_days": 7}, headers=admin_h).json() if r["product_id"] == world["vodka"])
    assert Decimal(row["used_base"]) == 0 and Decimal(row["count_loss_base"]) == 700
