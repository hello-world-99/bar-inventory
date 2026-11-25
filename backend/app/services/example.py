"""Example data: one day of the owner's POS report run through the real flow (agent-room reply 33, p. 3).

    python -m app.cli seed-example

A receipt marked "Example data" stocks the kitchen, the POS day (app/examples/pos_day.xlsx) is uploaded for the
previous business day, drinks are marked "not kitchen", and the usage is written off. Everything goes through
the same services as the UI, so the journal, the report and the dashboard show a real, consistent picture.
Not a migration: it is meant for a fresh install and refuses to run twice.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Location, PosItem, PosItemComponent, Product, Role, SalesImport, StockDocument, User
from app.schemas_docs import ReceiptIn, ReceiptLineIn
from app.schemas_sales import PostIn
from app.services import posting, sales

EXAMPLE_FILE = Path(__file__).resolve().parent.parent / "examples" / "pos_day.xlsx"
MARK = "Example data"

# sku, quantity, unit, price per product unit in won, minimum stock in the product unit (example values).
# Wings, fish and Philly buns are stocked short on purpose: after the day's sales they are below their minimum
# and show up red as running out (owner, 2026-11-25).
STOCK = [
    ("KIT-FRIES", "10", "kg", "4500", "3"),
    ("KIT-WINGS", "1", "kg", "9000", "1"),
    ("KIT-FISH", "5", "pcs", "3000", "3"),
    ("KIT-PHILLY-MEAT", "20", "pack", "6000", "5"),  # 20 packs = 4 kg
    ("KIT-BURGER-MEAT", "20", "pack", "5000", "5"),
    ("KIT-PHILLY-BUN", "3", "pcs", "800", "4"),
    ("KIT-BURGER-BUN", "20", "pcs", "700", "5"),
]


def seed_example(db: Session) -> str:
    if db.scalar(select(func.count()).select_from(StockDocument).where(StockDocument.comment == MARK)):
        return "Example data is already there; nothing done."
    admin = db.scalar(select(User).where(User.role == Role.admin, User.is_active).order_by(User.id))
    if admin is None:
        raise SystemExit("No active administrator: create one first")

    kitchen = db.scalar(select(Location).where(func.lower(Location.name) == "kitchen", Location.is_active))
    if kitchen is None:
        kitchen = Location(name="Kitchen", description="Example data", is_active=True)
        db.add(kitchen)
        db.flush()

    products = {p.sku: p for p in db.scalars(select(Product).where(Product.sku.like("KIT-%"), Product.is_active))}
    missing = [sku for sku, *_ in STOCK if sku not in products]
    if missing:
        raise SystemExit(f"Kitchen products are missing ({', '.join(missing)}); run the migrations first")

    day = sales.default_sales_date(db)
    start = sales.day_start(db, day)
    receipt = ReceiptIn(
        id=uuid.uuid4(),
        doc_date=start - timedelta(hours=1),  # stock arrived before the sales day
        comment=MARK,
        supplier="Example supplier",
        lines=[
            ReceiptLineIn(product_id=products[sku].id, location_id=kitchen.id, qty=Decimal(qty), qty_unit=unit, unit_price=Decimal(price))
            for sku, qty, unit, price, _ in STOCK
        ],
    )
    for sku, _, _, _, minimum in STOCK:
        p = products[sku]
        p.min_stock_base = Decimal(minimum) * p.unit_size
    posting.post_receipt(db, admin, receipt, posting.request_hash("receipt", receipt))

    imp = sales.upload(db, admin, uuid.uuid4(), day, "pos_day.xlsx (example)", EXAMPLE_FILE.read_bytes())
    # Every item without a norm in this day is a drink: hide them from "no norm" so the example reads cleanly.
    codes = [line.pos_code for line in imp.lines]
    has_norm = select(PosItemComponent.pos_item_id).where(PosItemComponent.pos_item_id == PosItem.id).exists()
    db.execute(update(PosItem).where(PosItem.code.in_(codes), ~has_norm).values(not_kitchen=True))
    db.flush()

    done = sales.post(db, admin, imp.id, PostIn(document_id=uuid.uuid4(), location_id=kitchen.id))
    db.commit()
    n = db.scalar(select(func.count()).select_from(SalesImport))
    return f"Example data added: receipt to '{kitchen.name}', POS day {day.isoformat()} written off ({done.status.value}); {n} report(s)."
