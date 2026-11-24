"""Login brute-force protection, including spoofed X-Forwarded-For (reply 6, K1/K3)."""

from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.ratelimit import SlidingWindowLimiter
from app.main import app


def _proxied_client() -> TestClient:
    # Same trust setup as production (uvicorn --proxy-headers --forwarded-allow-ips='*').
    return TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"))


def test_spoofed_forwarded_for_cannot_bypass_username_limit(admin):
    """Even if every request claims a different client IP, the per-username limit still blocks."""
    with _proxied_client() as c:
        codes = []
        for i in range(31):
            r = c.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers={"X-Forwarded-For": f"10.0.{i // 250}.{i % 250 + 1}"},
            )
            codes.append(r.status_code)
        assert codes[:30] == [401] * 30
        assert codes[30] == 429
        # The real password is refused too while the username is locked.
        r = c.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password123"},
            headers={"X-Forwarded-For": "10.9.9.9"},
        )
        assert r.status_code == 429


def test_per_ip_limit_with_forwarded_for(admin):
    with _proxied_client() as c:
        h = {"X-Forwarded-For": "203.0.113.7"}
        for _ in range(10):
            assert c.post("/api/v1/auth/login", json={"username": "admin", "password": "x"}, headers=h).status_code == 401
        assert c.post("/api/v1/auth/login", json={"username": "admin", "password": "x"}, headers=h).status_code == 429
        # another address is not affected by the per-IP limit
        ok = c.post("/api/v1/auth/login", json={"username": "admin", "password": "password123"},
                    headers={"X-Forwarded-For": "203.0.113.8"})
        assert ok.status_code == 200


def test_limiter_drops_idle_keys_and_caps_size(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("app.core.ratelimit.time.monotonic", lambda: now[0])
    lim = SlidingWindowLimiter(max_events=3, window_seconds=10, max_keys=100)

    for i in range(500):
        lim.hit(f"k{i}")
    assert len(lim) <= 100

    assert not lim.is_blocked("never-seen")
    assert "never-seen" not in lim._events  # reads do not create keys

    now[0] += 11
    lim.is_blocked("k499")
    assert "k499" not in lim._events  # expired key removed on access


def test_limiter_blocks_after_max_events(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.core.ratelimit.time.monotonic", lambda: now[0])
    lim = SlidingWindowLimiter(max_events=2, window_seconds=10)
    lim.hit("a")
    lim.hit("a")
    assert lim.is_blocked("a")
    now[0] = 10.5
    assert not lim.is_blocked("a")
