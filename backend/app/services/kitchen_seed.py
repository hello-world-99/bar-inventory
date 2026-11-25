"""Kitchen products and the POS norms confirmed by the owner (agent-room replies 30 and 32).

Run once by migration 0006 (and by tests, which truncate the tables). Plain SQL on a connection, so the
migration does not depend on the ORM models of a later version. Idempotent: existing products (by SKU) and
existing POS items (by code) are left alone. No stock and no prices are created.
"""

import logging
from decimal import Decimal

from sqlalchemy import Connection, text

log = logging.getLogger("alembic.runtime.migration")

# sku, name, unit, base_unit, unit_size
PRODUCTS = [
    ("KIT-FRIES", "French fries", "kg", "g", 1000),
    ("KIT-WINGS", "Chicken wings", "kg", "g", 1000),
    ("KIT-FISH", "Fish (portion)", "pcs", "pcs", 1),
    ("KIT-PHILLY-MEAT", "Philly steak meat", "pack", "g", 200),  # packs of 200 g, converted to grams (reply 37)
    ("KIT-BURGER-MEAT", "Burger meat", "pack", "g", 200),
    ("KIT-PHILLY-BUN", "Philly bun", "pcs", "pcs", 1),
    ("KIT-BURGER-BUN", "Burger bun", "pcs", "pcs", 1),
]

# POS code, name as in the POS, [(sku, qty in the product's base unit per sold unit)]
NORMS = [
    ("001783", "Fries", [("KIT-FRIES", 350)]),
    ("001542", "Half Fries", [("KIT-FRIES", 175)]),
    ("001779", "Fish & Chips", [("KIT-FRIES", 200), ("KIT-FISH", 1)]),
    ("001782", "Full wings", [("KIT-WINGS", 400)]),
    ("001781", "Half Wings", [("KIT-WINGS", 200)]),
    ("001981", "Philly", [("KIT-PHILLY-MEAT", 200), ("KIT-PHILLY-BUN", 1)]),  # no fries (owner, reply 32); 200 g = 1 pack
]
# The burger (175 g fries + 200 g burger meat + 1 burger bun) is not seeded: its POS code is unknown yet.

BASE_OF_SKU = {sku: base for sku, _, _, base, _ in PRODUCTS}


def seed(conn: Connection) -> None:
    cat = conn.scalar(text("SELECT id FROM categories WHERE code = 'kitchen'"))
    if cat is None:
        cat = conn.scalar(text("INSERT INTO categories (code, name) VALUES ('kitchen', 'Kitchen') RETURNING id"))

    for sku, name, unit, base, size in PRODUCTS:
        exists = conn.scalar(text("SELECT 1 FROM products WHERE lower(sku) = lower(:s) AND is_active"), {"s": sku})
        if not exists:
            conn.execute(
                text("INSERT INTO products (name, sku, category_id, unit, base_unit, unit_size) "
                     "VALUES (:n, :s, :c, CAST(:u AS product_unit), CAST(:b AS base_unit), :z)"),
                {"n": name, "s": sku, "c": cat, "u": unit, "b": base, "z": size},
            )

    for code, pos_name, components in NORMS:
        if conn.scalar(text("SELECT 1 FROM pos_items WHERE code = :c"), {"c": code}):
            continue
        rows = []
        for sku, qty in components:
            p = conn.execute(
                text("SELECT id, base_unit::text FROM products WHERE lower(sku) = lower(:s) AND is_active"), {"s": sku}
            ).first()
            if p is None or p[1] != BASE_OF_SKU[sku]:
                # e.g. KIT-FRIES already kept in pcs: 350 "g" would become 350 pieces (reply 32, N2)
                log.warning("kitchen seed: no norm for POS %s - product %s missing or not measured in %s", code, sku, BASE_OF_SKU[sku])
                rows = None
                break
            rows.append((p[0], Decimal(qty)))
        item = conn.scalar(text("INSERT INTO pos_items (code, name) VALUES (:c, :n) RETURNING id"), {"c": code, "n": pos_name})
        for product_id, qty in rows or []:
            conn.execute(
                text("INSERT INTO pos_item_components (pos_item_id, product_id, qty_base) VALUES (:i, :p, :q)"),
                {"i": item, "p": product_id, "q": qty},
            )
