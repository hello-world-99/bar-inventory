import uuid
from decimal import Decimal

from sqlalchemy import text

from app.models import StockBalance


def cat_id(client, h, code="alcohol"):
    return next(c["id"] for c in client.get("/api/v1/categories", headers=h).json() if c["code"] == code)


def make_product(client, h, **kw):
    body = {"name": "Vodka", "sku": "VOD-07", "category_id": cat_id(client, h), "unit": "bottle", "unit_size": "700",
            "purchase_price": "30000", "min_stock_base": "1400"} | kw
    r = client.post("/api/v1/products", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def make_location(client, h, name="Main storage"):
    r = client.post("/api/v1/locations", json={"name": name}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ categories
def test_seeded_categories(client, staff_h):
    codes = [c["code"] for c in client.get("/api/v1/categories", headers=staff_h).json()]
    assert codes == ["alcohol", "soft_drinks", "food_ingredients", "supplies", "other"]


def test_custom_category_and_builtin_rename_forbidden(client, admin_h):
    r = client.post("/api/v1/categories", json={"name": "Beer"}, headers=admin_h)
    assert r.status_code == 201 and r.json()["code"] is None
    assert client.post("/api/v1/categories", json={"name": "beer"}, headers=admin_h).status_code == 409
    alc = cat_id(client, admin_h)
    assert client.patch(f"/api/v1/categories/{alc}", json={"name": "Booze"}, headers=admin_h).status_code == 400


def test_staff_cannot_manage_catalog(client, staff_h):
    assert client.post("/api/v1/categories", json={"name": "X"}, headers=staff_h).status_code == 403
    assert client.post("/api/v1/locations", json={"name": "X"}, headers=staff_h).status_code == 403
    assert client.post("/api/v1/products", json={}, headers=staff_h).status_code == 403
    assert client.get("/api/v1/products", headers=staff_h).status_code == 200


# ------------------------------------------------------------------- locations
def test_location_crud_and_unique_active_name(client, admin_h):
    loc = make_location(client, admin_h, "Bar counter")
    assert client.post("/api/v1/locations", json={"name": " bar COUNTER "}, headers=admin_h).status_code == 409
    r = client.patch(f"/api/v1/locations/{loc['id']}", json={"is_active": False}, headers=admin_h)
    assert r.status_code == 200 and r.json()["is_active"] is False
    # name is free again among active locations
    again = make_location(client, admin_h, "Bar counter")
    # reactivating the old one now collides
    assert client.patch(f"/api/v1/locations/{loc['id']}", json={"is_active": True}, headers=admin_h).status_code == 409
    names = [x["id"] for x in client.get("/api/v1/locations?active=all", headers=admin_h).json()]
    assert set(names) == {loc["id"], again["id"]}


def test_cannot_deactivate_location_with_inventory_in_progress(client, db, admin, admin_h):
    loc = make_location(client, admin_h)
    db.execute(text("INSERT INTO inventories (location_id, started_by) VALUES (:l, :u)"), {"l": loc["id"], "u": admin.id})
    db.commit()
    r = client.patch(f"/api/v1/locations/{loc['id']}", json={"is_active": False}, headers=admin_h)
    assert r.status_code == 409
    assert client.get("/api/v1/locations", headers=admin_h).json()[0]["has_active_inventory"] is True


# -------------------------------------------------------------------- products
def test_create_bottle_product_and_units(client, admin_h):
    p = make_product(client, admin_h)
    assert p["base_unit"] == "ml" and Decimal(p["unit_size"]) == 700
    assert p["category_code"] == "alcohol"
    # decimals travel as strings
    assert isinstance(p["purchase_price"], str)

    kg = make_product(client, admin_h, name="Sugar", sku="SUG", unit="kg", unit_size=None, category_id=cat_id(client, admin_h, "food_ingredients"))
    assert kg["base_unit"] == "g" and Decimal(kg["unit_size"]) == 1000


def test_unit_size_rules(client, admin_h):
    c = cat_id(client, admin_h)
    base = {"name": "X", "sku": "X1", "category_id": c}
    assert client.post("/api/v1/products", json=base | {"unit": "bottle"}, headers=admin_h).status_code == 422
    assert client.post("/api/v1/products", json=base | {"unit": "l", "unit_size": "750"}, headers=admin_h).status_code == 422
    assert client.post("/api/v1/products", json=base | {"unit": "l", "unit_size": "1000"}, headers=admin_h).status_code == 201


def test_sku_unique_among_active_only(client, admin_h):
    p = make_product(client, admin_h)
    assert client.post("/api/v1/products", json={"name": "Dup", "sku": "vod-07", "category_id": cat_id(client, admin_h), "unit": "pcs"}, headers=admin_h).status_code == 409
    client.patch(f"/api/v1/products/{p['id']}", json={"is_active": False}, headers=admin_h)
    make_product(client, admin_h, name="Vodka v2")  # same SKU, old one inactive


def test_barcode_unique_and_clearable(client, admin_h):
    p = make_product(client, admin_h, barcode="4601234567890")
    r = client.post("/api/v1/products", json={"name": "Y", "sku": "Y", "category_id": cat_id(client, admin_h), "unit": "pcs", "barcode": "4601234567890"}, headers=admin_h)
    assert r.status_code == 409
    r = client.patch(f"/api/v1/products/{p['id']}", json={"barcode": None}, headers=admin_h)
    assert r.status_code == 200 and r.json()["barcode"] is None


def test_search_and_filters(client, admin_h):
    make_product(client, admin_h, name="Absolut Vodka", sku="ABS-1", barcode="111")
    make_product(client, admin_h, name="Tonic", sku="TON-1", unit="pcs", unit_size=None, category_id=cat_id(client, admin_h, "soft_drinks"))
    get = lambda qs: [p["sku"] for p in client.get(f"/api/v1/products?{qs}", headers=admin_h).json()["items"]]  # noqa: E731
    assert get("q=vodka") == ["ABS-1"]
    assert get("q=ton") == ["TON-1"]
    assert get("q=111") == ["ABS-1"]
    assert get(f"category_id={cat_id(client, admin_h, 'soft_drinks')}") == ["TON-1"]
    assert get("sort=name&order=desc") == ["TON-1", "ABS-1"]


def test_totals_value_low_stock_and_balances(client, db, admin_h):
    p = make_product(client, admin_h)  # 30000 per 700 ml bottle, min 1400 ml
    a, b = make_location(client, admin_h, "A"), make_location(client, admin_h, "B")
    db.add_all([
        StockBalance(product_id=p["id"], location_id=a["id"], qty_base=Decimal("700")),
        StockBalance(product_id=p["id"], location_id=b["id"], qty_base=Decimal("350")),
    ])
    db.commit()
    d = client.get(f"/api/v1/products/{p['id']}", headers=admin_h).json()
    assert Decimal(d["total_qty_base"]) == Decimal("1050")
    assert Decimal(d["stock_value"]) == Decimal("45000.00")  # 1.5 bottles * 30000
    assert d["is_low_stock"] is True
    assert {x["location_name"]: Decimal(x["qty_base"]) for x in d["balances"]} == {"A": 700, "B": 350}
    lows = client.get("/api/v1/products?low_stock=true", headers=admin_h).json()
    assert lows["total"] == 1
    assert client.get(f"/api/v1/locations", headers=admin_h).json()[0]["product_count"] == 1


def test_units_frozen_after_first_movement(client, db, admin, admin_h):
    p = make_product(client, admin_h)
    loc = make_location(client, admin_h)
    # unit change is fine before any movement
    r = client.patch(f"/api/v1/products/{p['id']}", json={"unit_size": "750"}, headers=admin_h)
    assert r.status_code == 200 and r.json()["units_locked"] is False

    doc = uuid.uuid4()
    db.execute(text("INSERT INTO stock_balances (product_id, location_id, qty_base) VALUES (:p, :l, 750)"), {"p": p["id"], "l": loc["id"]})
    db.execute(text("INSERT INTO stock_documents (id, type, status, doc_date, created_by, posted_by, posted_at) VALUES (:d, 'receipt', 'posted', now(), :u, :u, now())"), {"d": doc, "u": admin.id})
    db.execute(text("INSERT INTO stock_movements (document_id, product_id, location_id, delta_base, unit_cost_base, balance_after, doc_date, user_id) VALUES (:d, :p, :l, 750, 40, 750, now(), :u)"), {"d": doc, "p": p["id"], "l": loc["id"], "u": admin.id})
    db.commit()

    r = client.patch(f"/api/v1/products/{p['id']}", json={"unit_size": "700"}, headers=admin_h)
    assert r.status_code == 409
    r = client.patch(f"/api/v1/products/{p['id']}", json={"unit": "l"}, headers=admin_h)
    assert r.status_code == 409
    # unrelated fields still editable, and re-sending the same size is not a change
    r = client.patch(f"/api/v1/products/{p['id']}", json={"name": "Vodka 0.75", "unit_size": "750"}, headers=admin_h)
    assert r.status_code == 200 and r.json()["units_locked"] is True


def test_units_frozen_by_draft_document_line(client, db, admin, admin_h):
    p = make_product(client, admin_h)
    loc = make_location(client, admin_h)
    doc = uuid.uuid4()
    db.execute(text("INSERT INTO stock_documents (id, type, doc_date, created_by) VALUES (:d, 'receipt', now(), :u)"), {"d": doc, "u": admin.id})
    db.execute(text("INSERT INTO stock_document_lines (document_id, line_no, product_id, location_to_id, qty_base) VALUES (:d, 1, :p, :l, 700)"), {"d": doc, "p": p["id"], "l": loc["id"]})
    db.commit()
    assert client.patch(f"/api/v1/products/{p['id']}", json={"unit": "kg"}, headers=admin_h).status_code == 409


def test_search_treats_wildcards_literally(client, admin_h):
    make_product(client, admin_h, name="Syrup 50%", sku="SYR_50", unit="pcs", unit_size=None)
    make_product(client, admin_h, name="Syrup 500", sku="SYRA50", unit="pcs", unit_size=None)
    get = lambda q: [p["sku"] for p in client.get("/api/v1/products", params={"q": q}, headers=admin_h).json()["items"]]  # noqa: E731
    assert get("50%") == ["SYR_50"]
    assert get("syr_") == ["SYR_50"]


def test_manual_price_change_stamps_price_updated_at(client, admin_h):
    p = make_product(client, admin_h, purchase_price="0")
    assert p["price_updated_at"] is None
    r = client.patch(f"/api/v1/products/{p['id']}", json={"purchase_price": "31000"}, headers=admin_h)
    assert r.json()["price_updated_at"] is not None


def test_weights_validation(client, admin_h):
    r = client.post("/api/v1/products", json={"name": "G", "sku": "G", "category_id": cat_id(client, admin_h), "unit": "bottle", "unit_size": "700", "full_weight_g": "500", "empty_weight_g": "600"}, headers=admin_h)
    assert r.status_code == 422


def test_inactive_category_rejected(client, admin_h):
    c = client.post("/api/v1/categories", json={"name": "Old"}, headers=admin_h).json()
    client.patch(f"/api/v1/categories/{c['id']}", json={"is_active": False}, headers=admin_h)
    r = client.post("/api/v1/products", json={"name": "Z", "sku": "Z", "category_id": c["id"], "unit": "pcs"}, headers=admin_h)
    assert r.status_code == 422
