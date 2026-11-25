from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://bar:bar@db:5432/bar"
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    # Secure cookies need HTTPS (localhost is exempt in browsers). Set false only for plain-HTTP LAN use.
    cookie_secure: bool = True

    initial_admin_username: str | None = None
    initial_admin_password: str | None = None

    # Failed logins per (client IP, username).
    login_max_attempts: int = 10
    login_window_seconds: int = 300
    # Failed logins per username from any address (stops brute force spread over many IPs).
    login_user_max_attempts: int = 30
    login_user_window_seconds: int = 900

    # USD -> KRW rate source (app/services/fx.py): free, no key, HTTPS. Change it here if it ever moves.
    rate_url: str = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=KRW"
    rate_auto_update: bool = True  # the daily background fetch; tests turn it off


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
