"""Concurrency invariants (architecture section 11) with real parallel transactions."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_posting import assert_journal_consistent, balance, receipt, world  # noqa: F401  (fixture)

P = "/api/v1"


def _parallel(n, fn):
    barrier = threading.Barrier(n)

    def run(i):
        with TestClient(app) as c:
            barrier.wait()
            return fn(c, i)

    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(run, range(n)))


def test_two_write_offs_of_the_last_bottle(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="1")
    body = lambda: {"id": str(uuid.uuid4()), "reason": "breakage", "lines": [{"product_id": world["vodka"], "location_id": world["main"], "qty": "1"}]}  # noqa: E731
    codes = sorted(r.status_code for r in _parallel(2, lambda c, i: c.post(f"{P}/write-offs", json=body(), headers=staff_h)))
    assert codes == [201, 422]
    assert balance(db, world["vodka"], world["main"]) == 0
    assert_journal_consistent(db)


def test_many_parallel_write_offs_never_overdraw(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="5")
    body = lambda: {"id": str(uuid.uuid4()), "reason": "other", "lines": [{"product_id": world["vodka"], "location_id": world["main"], "qty": "1"}]}  # noqa: E731
    codes = [r.status_code for r in _parallel(8, lambda c, i: c.post(f"{P}/write-offs", json=body(), headers=staff_h))]
    assert codes.count(201) == 5 and codes.count(422) == 3
    assert balance(db, world["vodka"], world["main"]) == 0
    assert_journal_consistent(db)


def test_parallel_duplicate_post_creates_one_document(client, db, admin_h, world):
    body = {"id": str(uuid.uuid4()), "lines": [{"product_id": world["vodka"], "location_id": world["main"], "qty": "1", "unit_price": "14"}]}
    results = _parallel(4, lambda c, i: c.post(f"{P}/receipts", json=body, headers=admin_h))
    assert sorted(r.status_code for r in results) == [200, 200, 200, 201]
    assert {r.json()["id"] for r in results} == {body["id"]}
    assert balance(db, world["vodka"], world["main"]) == 700
    assert db.execute(text("SELECT count(*) FROM stock_movements")).scalar() == 1


def test_crossing_transfers_do_not_deadlock(client, db, admin_h, world):
    for loc in ("main", "bar"):
        receipt(client, admin_h, world, qty="20", location=loc)
        receipt(client, admin_h, world, qty="20", product="lime", price="4", location=loc)

    def go(c, i):
        a, b = (world["main"], world["bar"]) if i % 2 else (world["bar"], world["main"])
        lines = [{"product_id": world["vodka"], "qty": "1"}, {"product_id": world["lime"], "qty": "1"}]
        if i % 3 == 0:
            lines.reverse()
        return c.post(f"{P}/transfers", json={"id": str(uuid.uuid4()), "from_location_id": a, "to_location_id": b, "lines": lines}, headers=admin_h)

    codes = [r.status_code for r in _parallel(10, go)]
    assert codes == [201] * 10
    total = balance(db, world["vodka"], world["main"]) + balance(db, world["vodka"], world["bar"])
    assert total == Decimal(40 * 700)
    assert_journal_consistent(db)


def test_reversal_sees_inventory_completed_while_it_waited(client, engine, admin, admin_h, world):
    """P1 (reply 15): A1 runs under the balance locks, so an inventory that completes while the reversal
    waits for those locks is seen, and the reversal is refused instead of corrupting the stock."""
    doc = receipt(client, admin_h, world, qty="10").json()
    with engine.connect() as conn:
        tx = conn.begin()
        # what inventory completion will do: lock the pair's balance, then mark the inventory completed
        conn.execute(text("SELECT 1 FROM stock_balances WHERE product_id=:p AND location_id=:l FOR UPDATE"), {"p": world["vodka"], "l": world["main"]})
        inv = conn.execute(text(
            "INSERT INTO inventories (location_id, status, started_by, completed_by, completed_at) "
            "VALUES (:l, 'completed', :u, :u, clock_timestamp()) RETURNING id"), {"l": world["main"], "u": admin.id}).scalar()
        conn.execute(text(
            "INSERT INTO inventory_lines (inventory_id, product_id, expected_at_start_base, counted_base, expected_at_count_base, counted_at, counted_by) "
            "VALUES (:i, :p, 7000, 7000, 7000, clock_timestamp(), :u)"), {"i": inv, "p": world["vodka"], "u": admin.id})

        result = {}

        def rev():
            with TestClient(app) as c:
                result["r"] = c.post(f"{P}/documents/{doc['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h)

        t = threading.Thread(target=rev)
        t.start()
        time.sleep(0.7)
        assert t.is_alive(), "reversal must wait for the balance lock held by the completing inventory"
        tx.commit()
        t.join(10)
    assert result["r"].status_code == 409 and result["r"].json()["detail"]["code"] == "counted_after"


def test_unit_change_waits_for_in_flight_posting(client, engine, admin, admin_h, world):
    """P2: an in-flight posting holds the product FOR SHARE; a concurrent unit change must wait and then see the movement."""
    doc = uuid.uuid4()
    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(text("SELECT id FROM products WHERE id = :p FOR SHARE"), {"p": world["vodka"]})
        conn.execute(text("INSERT INTO stock_balances (product_id, location_id, qty_base) VALUES (:p, :l, 700)"), {"p": world["vodka"], "l": world["main"]})
        conn.execute(text("INSERT INTO stock_documents (id, type, doc_date, created_by) VALUES (:d, 'receipt', now(), :u)"), {"d": doc, "u": admin.id})
        conn.execute(text("INSERT INTO stock_document_lines (document_id, line_no, product_id, location_to_id, qty_base) VALUES (:d, 1, :p, :l, 700)"), {"d": doc, "p": world["vodka"], "l": world["main"]})
        conn.execute(text("UPDATE stock_documents SET status='posted', posted_by=:u, posted_at=now() WHERE id=:d"), {"d": doc, "u": admin.id})
        conn.execute(text("INSERT INTO stock_movements (document_id, product_id, location_id, delta_base, unit_cost_base, balance_after, doc_date, user_id) VALUES (:d, :p, :l, 700, 0.02, 700, now(), :u)"), {"d": doc, "p": world["vodka"], "l": world["main"], "u": admin.id})

        result = {}

        def patch():
            with TestClient(app) as c:
                result["r"] = c.patch(f"{P}/products/{world['vodka']}", json={"unit_size": "1000"}, headers=admin_h)

        t = threading.Thread(target=patch)
        t.start()
        time.sleep(0.7)
        assert t.is_alive(), "unit change must block while a posting holds the product"
        tx.commit()
        t.join(10)
    assert result["r"].status_code == 409
