from app.models import Role
from tests.conftest import auth_headers, make_user


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_login_me_and_refresh(client, admin):
    r = client.post("/api/v1/auth/login", json={"username": "ADMIN", "password": "password123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert "refresh_token" in r.cookies
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["username"] == "admin" and me["role"] == "admin"
    assert "manage_users" in me["permissions"]

    r2 = client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200 and r2.json()["access_token"]


def test_refresh_cookie_flags(client, admin):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "password123"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/auth" in cookie


def test_wrong_password_and_unknown_user(client, admin):
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"}).status_code == 401


def test_inactive_user_cannot_login(client, db):
    make_user(db, "gone", Role.staff, active=False)
    assert client.post("/api/v1/auth/login", json={"username": "gone", "password": "password123"}).status_code == 401


def test_login_rate_limit(client, admin):
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"})
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "password123"})
    assert r.status_code == 429


def test_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_staff_cannot_manage_users_or_settings(client, staff_h):
    assert client.get("/api/v1/users", headers=staff_h).status_code == 403
    assert client.patch("/api/v1/settings", json={"currency": "KRW"}, headers=staff_h).status_code == 403
    assert client.get("/api/v1/settings", headers=staff_h).status_code == 200


def test_admin_creates_user_and_deactivation_revokes_tokens(client, admin_h):
    r = client.post(
        "/api/v1/users",
        json={"username": "bob", "password": "password123", "role": "staff"},
        headers=admin_h,
    )
    assert r.status_code == 201
    bob_id = r.json()["id"]
    assert client.post("/api/v1/users", json={"username": "BOB", "password": "password123"}, headers=admin_h).status_code == 409

    bob_h = auth_headers(client, "bob")
    assert client.get("/api/v1/auth/me", headers=bob_h).status_code == 200
    assert client.patch(f"/api/v1/users/{bob_id}", json={"is_active": False}, headers=admin_h).status_code == 200
    assert client.get("/api/v1/auth/me", headers=bob_h).status_code == 401


def test_cannot_remove_last_admin_or_self(client, db, admin, admin_h):
    assert client.patch(f"/api/v1/users/{admin.id}", json={"is_active": False}, headers=admin_h).status_code == 409
    assert client.patch(f"/api/v1/users/{admin.id}", json={"role": "staff"}, headers=admin_h).status_code == 409
    other = make_user(db, "admin2", Role.admin)
    # demoting another admin is allowed while one active admin remains
    assert client.patch(f"/api/v1/users/{other.id}", json={"role": "staff"}, headers=admin_h).status_code == 200


def test_admin_cannot_reset_own_password_via_users_endpoint(client, admin, admin_h):
    r = client.patch(f"/api/v1/users/{admin.id}", json={"password": "newpassword1"}, headers=admin_h)
    assert r.status_code == 400
    assert client.get("/api/v1/auth/me", headers=admin_h).status_code == 200


def test_currency_decimals_limited_to_price_precision(client, admin_h):
    assert client.patch("/api/v1/settings", json={"currency_decimals": 3}, headers=admin_h).status_code == 422


def test_change_password_revokes_other_sessions(client, admin):
    h1 = auth_headers(client, "admin")
    r = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "password123", "new_password": "newpassword1"},
        headers=h1,
    )
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers=h1).status_code == 401
    h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=h2).status_code == 200


def test_settings_update_validation(client, admin_h):
    assert client.patch("/api/v1/settings", json={"timezone": "Mars/Base"}, headers=admin_h).status_code == 422
    r = client.patch(
        "/api/v1/settings",
        json={"currency": "KRW", "currency_decimals": 0, "timezone": "Asia/Seoul", "blind_count": True},
        headers=admin_h,
    )
    assert r.status_code == 200 and r.json()["currency"] == "KRW" and r.json()["blind_count"] is True
