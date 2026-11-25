"""Database-level guarantees of migration 0002 (independent of the API layer)."""

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import BACKEND_DIR, TEST_DB_URL


@pytest.fixture
def seed(db, admin):
    db.execute(text("INSERT INTO locations (id, name) VALUES (1, 'A'), (2, 'B')"))
    db.execute(text(
        "INSERT INTO products (id, name, sku, category_id, unit, base_unit, unit_size) "
        "VALUES (1, 'Vodka', 'V', (SELECT id FROM categories WHERE code='alcohol'), 'bottle', 'ml', 700)"
    ))
    db.execute(text("INSERT INTO stock_balances (product_id, location_id, qty_base) VALUES (1, 1, 0)"))
    db.commit()
    return admin


def _fails(db, sql, params=None, exc=IntegrityError):
    with pytest.raises(exc):
        db.execute(text(sql), params or {})
        db.flush()
    db.rollback()


def _doc(db, user_id, type_="receipt", **kw):
    d = uuid.uuid4()
    cols = {"id": d, "type": type_, "status": "posted", "doc_date": "now()", "created_by": user_id,
            "posted_by": user_id, "posted_at": "now()"} | kw
    names = ", ".join(cols)
    vals = ", ".join("now()" if v == "now()" else f":{k}" for k, v in cols.items())
    db.execute(text(f"INSERT INTO stock_documents ({names}) VALUES ({vals})"), {k: v for k, v in cols.items() if v != "now()"})
    return d


@pytest.mark.parametrize(
    "unit,base,size",
    [("l", "ml", 750), ("bottle", "g", 700), ("kg", "g", 1), ("pcs", "ml", 1), ("ml", "ml", 0)],
)
def test_product_unit_combo_check(db, unit, base, size):
    _fails(db, "INSERT INTO products (name, sku, category_id, unit, base_unit, unit_size) "
               "VALUES ('x','x',(SELECT id FROM categories LIMIT 1), :u, :b, :s)", {"u": unit, "b": base, "s": size})


def test_write_off_requires_reason_and_only_write_off_has_one(db, seed):
    _fails(db, "INSERT INTO stock_documents (id, type, doc_date, created_by) VALUES (:i, 'write_off', now(), :u)",
           {"i": uuid.uuid4(), "u": seed.id})
    _fails(db, "INSERT INTO stock_documents (id, type, doc_date, created_by, reason) VALUES (:i, 'receipt', now(), :u, 'other')",
           {"i": uuid.uuid4(), "u": seed.id})


def test_reversal_unique_and_required(db, seed):
    orig = _doc(db, seed.id)
    _doc(db, seed.id, "reversal", reversal_of=orig)
    db.commit()
    _fails(db, "INSERT INTO stock_documents (id, type, doc_date, created_by, reversal_of) VALUES (:i, 'reversal', now(), :u, :o)",
           {"i": uuid.uuid4(), "u": seed.id, "o": orig})
    _fails(db, "INSERT INTO stock_documents (id, type, doc_date, created_by) VALUES (:i, 'reversal', now(), :u)",
           {"i": uuid.uuid4(), "u": seed.id})


def test_posted_document_needs_poster(db, seed):
    _fails(db, "INSERT INTO stock_documents (id, type, status, doc_date, created_by) VALUES (:i, 'receipt', 'posted', now(), :u)",
           {"i": uuid.uuid4(), "u": seed.id})


def test_line_checks(db, seed):
    # draft parent, so only the CHECK constraints (not the immutability trigger) can reject these
    d = _doc(db, seed.id, status="draft", posted_by=None, posted_at=None)
    db.commit()
    base = "INSERT INTO stock_document_lines (document_id, line_no, product_id, location_from_id, location_to_id, qty_base) VALUES (:d, :n, 1, :f, :t, :q)"
    _fails(db, base, {"d": d, "n": 1, "f": None, "t": None, "q": 1})  # no location
    _fails(db, base, {"d": d, "n": 1, "f": 1, "t": 1, "q": 1})  # from == to
    _fails(db, base, {"d": d, "n": 1, "f": None, "t": 1, "q": 0})  # zero qty


def test_movements_need_balance_row_and_are_append_only(db, seed):
    d = _doc(db, seed.id)
    db.commit()
    ins = ("INSERT INTO stock_movements (document_id, product_id, location_id, delta_base, unit_cost_base, balance_after, doc_date, user_id) "
           "VALUES (:d, 1, :l, 700, 42.857143, 700, now(), :u)")
    _fails(db, ins, {"d": d, "l": 2, "u": seed.id})  # no balance row for (1, 2)
    db.execute(text(ins), {"d": d, "l": 1, "u": seed.id})
    db.commit()
    _fails(db, "UPDATE stock_movements SET delta_base = 1", exc=DBAPIError)
    _fails(db, "DELETE FROM stock_movements", exc=DBAPIError)


def test_posted_documents_and_their_lines_are_immutable(db, seed):
    d = _doc(db, seed.id, status="draft", posted_by=None, posted_at=None)
    db.execute(text("INSERT INTO stock_document_lines (document_id, line_no, product_id, location_to_id, qty_base) VALUES (:d, 1, 1, 1, 700)"), {"d": d})
    # draft: lines and header are editable
    db.execute(text("UPDATE stock_document_lines SET qty_base = 1400 WHERE document_id = :d"), {"d": d})
    db.execute(text("UPDATE stock_documents SET comment = 'x' WHERE id = :d"), {"d": d})
    # the one allowed transition
    db.execute(text("UPDATE stock_documents SET status='posted', posted_by=:u, posted_at=now() WHERE id=:d"), {"d": d, "u": seed.id})
    db.commit()

    _fails(db, "UPDATE stock_document_lines SET qty_base = 7 WHERE document_id = :d", {"d": d})
    _fails(db, "DELETE FROM stock_document_lines WHERE document_id = :d", {"d": d})
    _fails(db, "INSERT INTO stock_document_lines (document_id, line_no, product_id, location_to_id, qty_base) VALUES (:d, 2, 1, 1, 1)", {"d": d})
    _fails(db, "UPDATE stock_documents SET doc_date = now() - interval '1 day' WHERE id = :d", {"d": d})
    _fails(db, "UPDATE stock_documents SET status = 'draft', posted_by = NULL, posted_at = NULL WHERE id = :d", {"d": d})
    _fails(db, "DELETE FROM stock_documents WHERE id = :d", {"d": d})

    # moving a line out of a posted document into a draft is rejected too
    d2 = _doc(db, seed.id, status="draft", posted_by=None, posted_at=None)
    db.commit()
    _fails(db, "UPDATE stock_document_lines SET document_id = :d2 WHERE document_id = :d", {"d": d, "d2": d2})


def test_draft_document_can_be_deleted_with_lines(db, seed):
    d = _doc(db, seed.id, status="draft", posted_by=None, posted_at=None)
    db.execute(text("INSERT INTO stock_document_lines (document_id, line_no, product_id, location_to_id, qty_base) VALUES (:d, 1, 1, 1, 700)"), {"d": d})
    db.commit()
    db.execute(text("DELETE FROM stock_documents WHERE id = :d"), {"d": d})
    db.commit()
    assert db.scalar(text("SELECT count(*) FROM stock_document_lines")) == 0


def test_product_weight_must_be_positive(db):
    _fails(db, "INSERT INTO products (name, sku, category_id, unit, base_unit, unit_size, full_weight_g) "
               "VALUES ('x','x',(SELECT id FROM categories LIMIT 1), 'bottle', 'ml', 700, -5)")


def test_one_inventory_in_progress_per_location(db, seed):
    db.execute(text("INSERT INTO inventories (location_id, started_by) VALUES (1, :u)"), {"u": seed.id})
    db.commit()
    _fails(db, "INSERT INTO inventories (location_id, started_by) VALUES (1, :u)", {"u": seed.id})
    db.execute(text("UPDATE inventories SET status='completed', completed_at=now(), completed_by=:u"), {"u": seed.id})
    db.execute(text("INSERT INTO inventories (location_id, started_by) VALUES (1, :u)"), {"u": seed.id})
    db.commit()


def test_inventory_line_count_fields_all_or_nothing(db, seed):
    db.execute(text("INSERT INTO inventories (id, location_id, started_by) VALUES (1, 1, :u)"), {"u": seed.id})
    db.commit()
    _fails(db, "INSERT INTO inventory_lines (inventory_id, product_id, expected_at_start_base, counted_base) VALUES (1, 1, 0, 5)")


def test_migrations_downgrade_and_upgrade_roundtrip(engine):
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.downgrade(cfg, "0001")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM categories WHERE code IS NOT NULL")) == 6  # 5 from 0002 + kitchen (0006)
        assert c.scalar(text("SELECT count(*) FROM pos_item_components")) == 8  # owner-confirmed norms (0006)
