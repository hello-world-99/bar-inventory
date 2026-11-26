from decimal import Decimal

from tests.test_posting import receipt, world, write_off  # noqa: F401  (fixture)

P = "/api/v1"


def test_dashboard_numbers(client, admin_h, staff_h, world):
    client.patch(f"{P}/products/{world['vodka']}", json={"min_stock_base": "2100"}, headers=admin_h)  # 3 bottles
    receipt(client, admin_h, world, qty="2", price="14.00")  # 2 bottles: low
    receipt(client, admin_h, world, qty="1", product="lime", price="4.00", location="bar")
    write_off(client, admin_h, world, "1", product="lime", location="bar")  # lime at bar: 0
    assert write_off(client, admin_h, world, "1", product="lime", location="bar").status_code == 422  # never below zero

    d = client.get(f"{P}/dashboard", headers=staff_h).json()
    assert d["product_count"] == 2 and d["location_count"] == 2
    assert Decimal(d["stock_value"]) == Decimal("28")  # 28 vodka, lime used up
    assert d["in_stock_count"] == 1
    assert d["low_stock_count"] == 1 and d["low_stock"][0]["product_id"] == world["vodka"]
    assert d["negative_count"] == 0
    assert len(d["recent_receipts"]) == 2 and len(d["recent_write_offs"]) == 1
    values = {x["name"]: Decimal(x["value"]) for x in d["by_location"]}
    assert values["Main"] == Decimal(28) and values.get("Bar", Decimal(0)) == 0


def test_dashboard_requires_login(client):
    assert client.get(f"{P}/dashboard").status_code == 401


def test_dashboard_parts_add_up_and_skip_cancelled_counts(client, admin_h, world):
    receipt(client, admin_h, world, qty="2", price="14.00")  # Main: 28
    receipt(client, admin_h, world, qty="1", price="14.00", location="bar")  # Bar: 14
    assert client.patch(f"{P}/locations/{world['bar']}", json={"is_active": False}, headers=admin_h).status_code == 200
    for _ in range(6):
        inv = client.post(f"{P}/inventories", json={"location_id": world["main"]}, headers=admin_h).json()
        assert client.post(f"{P}/inventories/{inv['id']}/cancel", headers=admin_h).status_code == 200
    d = client.get(f"{P}/dashboard", headers=admin_h).json()
    assert sum(Decimal(x["value"]) for x in d["by_location"]) == Decimal(d["stock_value"]) == Decimal(42)
    assert [(x["name"], x["is_active"]) for x in d["by_location"]] == [("Main", True), ("Bar", False)]
    assert d["recent_inventories"] == []
