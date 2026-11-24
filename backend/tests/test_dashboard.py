from decimal import Decimal

from tests.test_posting import receipt, world, write_off  # noqa: F401  (fixture)

P = "/api/v1"


def test_dashboard_numbers(client, admin_h, staff_h, world):
    client.patch(f"{P}/products/{world['vodka']}", json={"min_stock_base": "2100"}, headers=admin_h)  # 3 bottles
    receipt(client, admin_h, world, qty="2", price="14.00")  # 2 bottles: low
    receipt(client, admin_h, world, qty="1", product="lime", price="4.00", location="bar")
    write_off(client, admin_h, world, "1", product="lime", location="bar", allow_negative=True)
    write_off(client, admin_h, world, "1", product="lime", location="bar", allow_negative=True)  # lime at bar: -1 kg

    d = client.get(f"{P}/dashboard", headers=staff_h).json()
    assert d["product_count"] == 2 and d["location_count"] == 2
    assert Decimal(d["stock_value"]) == Decimal("24")  # 28 vodka - 4 lime
    assert d["in_stock_count"] == 1
    assert d["low_stock_count"] == 1 and d["low_stock"][0]["product_id"] == world["vodka"]
    assert d["negative_count"] == 1
    assert len(d["recent_receipts"]) == 2 and len(d["recent_write_offs"]) == 2
    assert {x["name"]: Decimal(x["value"]) for x in d["by_location"]} == {"Main": Decimal(28), "Bar": Decimal(-4)}


def test_dashboard_requires_login(client):
    assert client.get(f"{P}/dashboard").status_code == 401
