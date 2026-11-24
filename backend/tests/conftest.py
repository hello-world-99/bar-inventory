import os

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-0123")
os.environ.setdefault("COOKIE_SECURE", "false")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
# The suite drops and recreates the whole schema. Refuse anything that is not clearly a test database,
# so a misconfigured environment can never wipe the live bar database.
if not (TEST_DB_URL and (make_url(TEST_DB_URL).database or "").endswith("_test")):
    raise RuntimeError(f"TEST_DATABASE_URL must point to a database whose name ends with '_test' (got {TEST_DB_URL!r})")
os.environ["DATABASE_URL"] = TEST_DB_URL  # make the app use the test database everywhere

from app.api.v1.auth import login_limiter, user_login_limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESERVED_TABLES = {"alembic_version", "settings"}
# Re-created after every test because TRUNCATE wipes the rows seeded by migration 0002.
SEED_CATEGORIES_SQL = (
    "INSERT INTO categories (code, name) VALUES "
    "('alcohol','Alcohol'),('soft_drinks','Soft drinks'),('food_ingredients','Food & ingredients'),"
    "('supplies','Supplies'),('other','Other')"
)


def _ensure_database(url: str) -> None:
    u = make_url(url)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": u.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{u.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine():
    _ensure_database(TEST_DB_URL)
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(TEST_DB_URL)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_db(engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
            if r[0] not in PRESERVED_TABLES
        ]
        if tables:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
        conn.execute(text("DELETE FROM settings; INSERT INTO settings (id) VALUES (1)"))
        conn.execute(text(SEED_CATEGORIES_SQL))
    login_limiter.clear()
    user_login_limiter.clear()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def make_user(db: Session, username: str, role: Role, password: str = "password123", active: bool = True) -> User:
    u = User(
        username=username,
        full_name="",
        password_hash=hash_password(password),
        role=role,
        is_active=active,
        token_version=0,
    )
    db.add(u)
    db.commit()
    return u


def auth_headers(client: TestClient, username: str, password: str = "password123") -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(db: Session) -> User:
    return make_user(db, "admin", Role.admin)


@pytest.fixture
def staff(db: Session) -> User:
    return make_user(db, "staff", Role.staff)


@pytest.fixture
def admin_h(client: TestClient, admin: User) -> dict[str, str]:
    return auth_headers(client, "admin")


@pytest.fixture
def staff_h(client: TestClient, staff: User) -> dict[str, str]:
    return auth_headers(client, "staff")
