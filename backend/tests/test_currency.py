"""Money in won, display in KRW or USD at an exchange rate (agent-room replies 33-35). No real network here."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.services import fx
from tests.test_posting import receipt, world  # noqa: F401  (fixture)

P = "/api/v1"
GOOD = b'{"amount":1.0,"base":"USD","date":"2026-11-24","rates":{"KRW":1400.5}}'


@pytest.fixture(autouse=True)
def rate_fetch_on(request, monkeypatch):
    """The fetch is off by default (owner, reply 69); these tests cover it when it is turned on."""
    if "rate_off" not in request.keywords:
        monkeypatch.setattr(get_settings(), "rate_auto_update", True)


@pytest.mark.rate_off
def test_rate_fetch_is_off_by_default(client, admin_h, monkeypatch):
    called = []
    monkeypatch.setattr(fx, "fetch", lambda url: called.append(url) or GOOD)
    r = client.post(f"{P}/settings/rate/update", headers=admin_h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "rate_disabled" and called == []
    assert get_settings().rate_auto_update is False
    import threading

    assert not [t for t in threading.enumerate() if t.name == "fx-rate"]  # the background fetch did not start


def settings(client, h):
    return client.get(f"{P}/settings", headers=h).json()


def patch(client, h, **body):
    return client.patch(f"{P}/settings", json=body, headers=h)


def manual_rate(client, h, rate="1400"):
    assert patch(client, h, rate_mode="manual").status_code == 200
    r = patch(client, h, usd_krw_rate=rate)
    assert r.status_code == 200, r.text
    return r.json()


def test_won_by_default_and_usd_needs_a_rate(client, admin_h):
    s = settings(client, admin_h)
    assert (s["currency"], s["currency_decimals"], s["rate_mode"], s["usd_krw_rate"]) == ("KRW", 0, "auto", None)
    r = patch(client, admin_h, currency="USD")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "rate_required"
    assert settings(client, admin_h)["currency"] == "KRW"
    assert patch(client, admin_h, currency="EUR").status_code == 422  # only KRW and USD


def test_manual_rate_then_usd(client, admin_h):
    r = patch(client, admin_h, usd_krw_rate="1400")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "rate_is_automatic"
    s = manual_rate(client, admin_h)
    assert Decimal(s["usd_krw_rate"]) == 1400 and s["rate_source"] == "manual"
    s = patch(client, admin_h, currency="USD").json()
    assert (s["currency"], s["currency_decimals"]) == ("USD", 2)
    s = patch(client, admin_h, currency="KRW").json()
    assert (s["currency"], s["currency_decimals"]) == ("KRW", 0)


def test_automatic_rate_good_answer(client, admin_h, monkeypatch):
    calls = []
    monkeypatch.setattr(fx, "fetch", lambda url: calls.append(url) or GOOD)
    r = client.post(f"{P}/settings/rate/update", headers=admin_h)
    assert r.status_code == 200
    s = r.json()
    assert Decimal(s["usd_krw_rate"]) == Decimal("1400.5") and s["rate_date"] == "2026-11-24" and s["rate_error"] is None
    assert s["rate_source"] == "api.frankfurter.dev" and calls[0].startswith("https://")
    assert patch(client, admin_h, currency="USD").status_code == 200


@pytest.mark.parametrize(
    "answer,error",
    [
        (b"<html>maintenance</html>", "unexpected answer"),
        (b'{"rates":{"EUR":0.9}}', "unexpected answer"),
        (b'{"rates":{"KRW":"1400"}}', "unexpected answer"),
        (b'{"rates":{"KRW":14.0}}', "outside"),
        (b'{"rates":{"KRW":140000}}', "outside"),
        (fx.RateError("source unreachable (TimeoutError)"), "unreachable"),
    ],
)
def test_automatic_rate_failures_keep_the_last_rate(client, admin_h, monkeypatch, answer, error):
    monkeypatch.setattr(fx, "fetch", lambda url: GOOD)
    client.post(f"{P}/settings/rate/update", headers=admin_h)

    def bad(url):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(fx, "fetch", bad)
    r = client.post(f"{P}/settings/rate/update", headers=admin_h)
    assert r.status_code == 200  # a failure never breaks the app
    s = r.json()
    assert Decimal(s["usd_krw_rate"]) == Decimal("1400.5") and error in s["rate_error"]


def test_manual_mode_is_never_overwritten(client, db, admin_h, monkeypatch):
    manual_rate(client, admin_h, "1350")
    monkeypatch.setattr(fx, "fetch", lambda url: GOOD)
    r = client.post(f"{P}/settings/rate/update", headers=admin_h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "rate_is_manual"
    fx.update_rate(db, force=True)  # the background job too
    assert Decimal(settings(client, admin_h)["usd_krw_rate"]) == 1350


def test_only_https_sources():
    with pytest.raises(fx.RateError):
        fx._http_get("http://example.com/rate")


def test_receipt_priced_in_dollars_is_stored_in_won(client, db, admin_h, world):
    manual_rate(client, admin_h, "1400")
    r = receipt(client, admin_h, world, qty="2", price="14.00", price_currency="USD")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert Decimal(doc["lines"][0]["unit_price"]) == 19600 and Decimal(doc["price_rate"]) == 1400
    assert Decimal(client.get(f"{P}/products/{world['vodka']}", headers=admin_h).json()["purchase_price"]) == 19600
    # whole won, rounded on the server
    r = receipt(client, admin_h, world, qty="1", price="0.01", price_currency="USD", product="lime")
    assert Decimal(r.json()["lines"][0]["unit_price"]) == 14


def test_product_price_in_dollars(client, admin_h, world):
    manual_rate(client, admin_h, "1400")
    r = client.patch(f"{P}/products/{world['lime']}", json={"purchase_price": "2.50", "price_currency": "USD"}, headers=admin_h)
    assert r.status_code == 200 and Decimal(r.json()["purchase_price"]) == 3500


def test_dollar_prices_need_a_rate(client, admin_h, world):
    r = receipt(client, admin_h, world, price="14.00", price_currency="USD")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "rate_required"


def test_changing_currency_or_rate_changes_no_stored_number(client, db, admin_h, world):
    receipt(client, admin_h, world, qty="3", price="19600")

    def snapshot():
        return (
            db.execute(text("SELECT id, purchase_price FROM products ORDER BY id")).all(),
            db.execute(text("SELECT id, delta_base, unit_cost_base, balance_after FROM stock_movements ORDER BY id")).all(),
            db.execute(text("SELECT id, unit_price, unit_cost_base FROM stock_document_lines ORDER BY id")).all(),
            db.execute(text("SELECT product_id, location_id, qty_base FROM stock_balances ORDER BY 1, 2")).all(),
        )

    before = snapshot()
    manual_rate(client, admin_h, "1400")
    patch(client, admin_h, currency="USD")
    patch(client, admin_h, usd_krw_rate="1500")
    patch(client, admin_h, currency="KRW")
    db.expire_all()
    assert snapshot() == before


def test_large_won_amounts_fit(client, admin_h, world):
    """A day's revenue is millions of won; prices of hundreds of thousands must post fine."""
    r = receipt(client, admin_h, world, qty="100", price="950000", product="lime")  # 100 kg at 950 000 per kg
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["total_amount"]) == 95_000_000
