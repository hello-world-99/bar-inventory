"""Inventory counts (architecture section 5): the formula, its counterexamples, blind mode, completion rules."""

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_posting import assert_journal_consistent, balance, receipt, world, write_off  # noqa: F401  (fixture)

P = "/api/v1"


def start(client, h, w, location="main"):
    r = client.post(f"{P}/inventories", json={"location_id": w[location]}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def count(client, h, inv, product, parts, **kw):
    body = {"parts": [{"qty": str(q), "qty_unit": u} for q, u in parts]} | kw
    return client.put(f"{P}/inventories/{inv['id']}/lines/{product}", json=body, headers=h)


def complete(client, h, inv, **kw):
    return client.post(f"{P}/inventories/{inv['id']}/complete", json=kw, headers=h)


def line(detail, product):
    return next(x for x in detail["lines"] if x["product_id"] == product)


# ---------------------------------------------------------------- basics
def test_start_snapshot_and_one_active_per_location(client, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="3")
    receipt(client, admin_h, world, qty="1", product="lime", price="4")
    write_off(client, admin_h, world, "1", product="lime")  # lime balance row exists with 0
    inv = start(client, staff_h, world)
    assert inv["status"] == "in_progress" and inv["line_count"] == 2
    assert Decimal(line(inv, world["lime"])["expected_at_start_base"]) == 0  # zero rows are counted too
    r = client.post(f"{P}/inventories", json={"location_id": world["main"]}, headers=admin_h)
    assert r.status_code == 409
    assert client.post(f"{P}/inventories", json={"location_id": world["bar"]}, headers=admin_h).status_code == 201


def test_partial_bottle_count_and_version_conflict(client, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="3")
    inv = start(client, staff_h, world)
    r = count(client, staff_h, inv, world["vodka"], [(2, "bottle"), (350, "ml")])  # 700 ml bottles
    assert r.status_code == 200, r.text
    ln = r.json()
    assert Decimal(ln["counted_base"]) == 1750 and ln["version"] == 2
    # someone else counted meanwhile: the stale version is refused
    assert count(client, admin_h, inv, world["vodka"], [(1, "bottle")], version=2).status_code == 200
    r = count(client, staff_h, inv, world["vodka"], [(3, "bottle")], version=2)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_conflict"


def test_product_found_outside_snapshot_can_be_added(client, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="1")
    inv = start(client, staff_h, world)
    r = count(client, staff_h, inv, world["lime"], [(0.5, "kg")])
    assert r.status_code == 200 and Decimal(r.json()["counted_base"]) == 500
    done = complete(client, admin_h, inv).json()
    assert done["status"] == "completed"
    assert balance_of(client, admin_h, world["lime"]) == 500


def balance_of(client, h, product):
    return Decimal(client.get(f"{P}/products/{product}", headers=h).json()["total_qty_base"])


def test_blind_mode_hides_expected_from_staff_only(client, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="2")
    client.patch(f"{P}/settings", json={"blind_count": True}, headers=admin_h)
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(1, "bottle")])
    seen_by_staff = client.get(f"{P}/inventories/{inv['id']}", headers=staff_h).json()
    ln = line(seen_by_staff, world["vodka"])
    assert seen_by_staff["blind"] is True and ln["expected_base"] is None and ln["diff_base"] is None and seen_by_staff["net_cost"] is None
    seen_by_admin = client.get(f"{P}/inventories/{inv['id']}", headers=admin_h).json()
    assert Decimal(line(seen_by_admin, world["vodka"])["diff_base"]) == -700


def test_staff_cannot_complete_or_cancel(client, admin_h, staff_h, world):
    receipt(client, admin_h, world)
    inv = start(client, staff_h, world)
    assert complete(client, staff_h, inv).status_code == 403
    assert client.post(f"{P}/inventories/{inv['id']}/cancel", headers=staff_h).status_code == 403


# ------------------------------------------------------- completion results
def test_completion_makes_counts_the_new_balances(client, db, admin_h, staff_h, world):
    """Requirement 2.5: after confirmation the counted quantities become the book quantities."""
    receipt(client, admin_h, world, qty="5")  # 3500 ml
    receipt(client, admin_h, world, qty="2", product="lime", price="4.00")  # 2000 g
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(4, "bottle"), (200, "ml")])  # 3000: shortage 500 ml
    count(client, staff_h, inv, world["lime"], [(2, "kg")])  # exact
    done = complete(client, admin_h, inv).json()
    assert done["status"] == "completed" and done["closed_by_name"] == "admin"
    assert balance(db, world["vodka"], world["main"]) == 3000
    assert balance(db, world["lime"], world["main"]) == 2000
    v = line(done, world["vodka"])
    assert Decimal(v["diff_base"]) == -500 and Decimal(v["diff_cost"]) == Decimal("-10.000000")  # 500 ml * 0.02
    assert Decimal(done["net_cost"]) == Decimal("-10.000000")
    doc = client.get(f"{P}/documents/{done['adjustment_document_id']}", headers=admin_h).json()
    assert doc["type"] == "inventory_adjustment" and doc["inventory_id"] == inv["id"]
    assert len(doc["lines"]) == 1  # exact counts produce no movement
    assert_journal_consistent(db)
    # closed for good
    assert complete(client, admin_h, inv).status_code == 409
    assert count(client, staff_h, inv, world["vodka"], [(1, "bottle")]).status_code == 409


def test_uncounted_lines_are_left_alone_unless_zeroed(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="2")
    receipt(client, admin_h, world, qty="1", product="lime", price="4")
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(2, "bottle")])
    complete(client, admin_h, inv)
    assert balance(db, world["lime"], world["main"]) == 1000  # not counted -> untouched

    inv2 = start(client, staff_h, world)
    count(client, staff_h, inv2, world["vodka"], [(2, "bottle")])
    complete(client, admin_h, inv2, zero_uncounted=True)
    assert balance(db, world["lime"], world["main"]) == 0
    assert_journal_consistent(db)


def test_nothing_counted_cannot_complete_and_cancel_changes_nothing(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="2")
    inv = start(client, staff_h, world)
    assert complete(client, admin_h, inv).json()["detail"]["code"] == "nothing_counted"
    count(client, staff_h, inv, world["vodka"], [(0, "bottle")])
    r = client.post(f"{P}/inventories/{inv['id']}/cancel", headers=admin_h).json()
    assert r["status"] == "cancelled" and r["closed_at"] is not None
    assert balance(db, world["vodka"], world["main"]) == 1400
    assert client.patch(f"{P}/locations/{world['main']}", json={"is_active": False}, headers=admin_h).status_code == 200


# --------------------------------------------- the formula: counterexamples
def test_case_a_write_off_after_count(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="5")
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(5, "bottle")])
    write_off(client, staff_h, world, "1")  # after the count: shelf now has 4
    complete(client, admin_h, inv)
    assert balance(db, world["vodka"], world["main"]) == 4 * 700


def test_case_b_write_off_before_count(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="5")
    inv = start(client, staff_h, world)
    write_off(client, staff_h, world, "1")
    count(client, staff_h, inv, world["vodka"], [(4, "bottle")])
    complete(client, admin_h, inv)
    assert balance(db, world["vodka"], world["main"]) == 4 * 700


def test_offline_count_uploaded_later_with_skewed_clock(client, db, admin_h, staff_h, world):
    """Counted 4 bottles; a write-off happened before the upload; the tablet clock is 10 minutes behind."""
    receipt(client, admin_h, world, qty="5")
    inv = start(client, staff_h, world)
    time.sleep(1.2)
    skew = timedelta(minutes=10)
    counted_device = datetime.now(UTC) - skew  # device clock shows 10 min less
    time.sleep(1.2)
    write_off(client, staff_h, world, "1")  # physically after the count
    sent_device = datetime.now(UTC) - skew
    r = count(client, staff_h, inv, world["vodka"], [(5, "bottle")], counted_at=counted_device.isoformat(), sent_at=sent_device.isoformat())
    assert r.status_code == 200
    complete(client, admin_h, inv)
    assert balance(db, world["vodka"], world["main"]) == 4 * 700  # 5 counted, then 1 written off


def test_fact_1_reversal_during_count(client, db, admin_h, staff_h, world):
    """Reply 15: receipt of 70 instead of 7, counted 7, then the receipt is reversed -> 7, not -63."""
    bad = receipt(client, admin_h, world, qty="70").json()
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(7, "bottle")])
    r = client.post(f"{P}/documents/{bad['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h)
    assert r.status_code == 201, r.text
    complete(client, admin_h, inv)
    assert balance(db, world["vodka"], world["main"]) == 7 * 700
    assert_journal_consistent(db)


def test_fact_2_backdated_receipt_entered_after_count(client, db, admin_h, staff_h, world):
    """Reply 15: 4 on the books, morning delivery of 6 shelved, 10 counted at night, receipt typed in later
    with its real morning time -> 10, not 16."""
    morning = datetime.now(UTC) - timedelta(hours=3)
    receipt(client, admin_h, world, qty="4", doc_date=(morning - timedelta(hours=1)).isoformat())
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(10, "bottle")])
    r = receipt(client, staff_h, world, qty="6", doc_date=morning.isoformat())  # inventory still in progress: allowed
    assert r.status_code == 201, r.text
    complete(client, admin_h, inv)
    assert balance(db, world["vodka"], world["main"]) == 10 * 700


# --------------------------------------------- interaction with documents
def test_after_completion_absorbed_documents_are_protected(client, admin_h, staff_h, world):
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    doc = receipt(client, admin_h, world, qty="3", doc_date=old).json()
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(3, "bottle")])
    complete(client, admin_h, inv)
    # reversal of a document the count already contains -> refused (A1)
    r = client.post(f"{P}/documents/{doc['id']}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "counted_after"
    # a document dated before the count -> backdate rules
    r = write_off(client, staff_h, world, "1", doc_date=old)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "backdate_forbidden"


def test_completion_waits_for_in_flight_posting_and_includes_it(client, engine, db, admin, admin_h, staff_h, world):
    """Reply 17 P1: completion queues behind a posting holding the balance lock; afterwards the posting is
    part of the expected quantity and its reversal is refused (completed_at is read after the locks)."""
    receipt(client, admin_h, world, qty="5")
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(5, "bottle")])  # what is on the shelf at counting time
    time.sleep(0.05)

    # An in-flight receipt dated before the count: it holds the balance lock while completion starts.
    doc = uuid.uuid4()
    before_count = datetime.now(UTC) - timedelta(minutes=30)
    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(text("SELECT 1 FROM stock_balances WHERE product_id=:p AND location_id=:l FOR UPDATE"), {"p": world["vodka"], "l": world["main"]})
        result = {}

        def finish():
            with TestClient(app) as c:
                result["r"] = complete(c, admin_h, inv)

        t = threading.Thread(target=finish)
        t.start()
        time.sleep(0.7)
        assert t.is_alive(), "completion must wait for the balance lock"
        conn.execute(text("INSERT INTO stock_documents (id, type, doc_date, created_by) VALUES (:d, 'receipt', :dd, :u)"), {"d": doc, "dd": before_count, "u": admin.id})
        conn.execute(text("INSERT INTO stock_document_lines (document_id, line_no, product_id, location_to_id, qty_base, unit_price, unit_cost_base) VALUES (:d, 1, :p, :l, 700, 14, 0.02)"), {"d": doc, "p": world["vodka"], "l": world["main"]})
        conn.execute(text("UPDATE stock_documents SET status='posted', posted_by=:u, posted_at=clock_timestamp() WHERE id=:d"), {"d": doc, "u": admin.id})
        conn.execute(text("UPDATE stock_balances SET qty_base = qty_base + 700 WHERE product_id=:p AND location_id=:l"), {"p": world["vodka"], "l": world["main"]})
        conn.execute(text("INSERT INTO stock_movements (document_id, product_id, location_id, delta_base, unit_cost_base, balance_after, doc_date, user_id) VALUES (:d, :p, :l, 700, 0.02, 4200, :dd, :u)"), {"d": doc, "p": world["vodka"], "l": world["main"], "dd": before_count, "u": admin.id})
        tx.commit()
        t.join(10)
    assert result["r"].status_code == 200, result["r"].text
    assert balance(db, world["vodka"], world["main"]) == 5 * 700  # the count wins; the late receipt was absorbed
    r = client.post(f"{P}/documents/{doc}/reverse", json={"id": str(uuid.uuid4())}, headers=admin_h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "counted_after"
    assert_journal_consistent(db)


def test_parallel_completion_only_once(client, db, admin_h, staff_h, world):
    receipt(client, admin_h, world, qty="5")
    inv = start(client, staff_h, world)
    count(client, staff_h, inv, world["vodka"], [(3, "bottle")])
    barrier = threading.Barrier(3)
    codes = []

    def go():
        with TestClient(app) as c:
            barrier.wait()
            codes.append(complete(c, admin_h, inv).status_code)

    threads = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert sorted(codes) == [200, 409, 409]
    assert balance(db, world["vodka"], world["main"]) == 3 * 700
    assert db.execute(text("SELECT count(*) FROM stock_documents WHERE type='inventory_adjustment'")).scalar() == 1
