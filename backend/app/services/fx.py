"""USD -> KRW exchange rate for display and price entry in dollars (agent-room replies 34-35).

All money is stored in won. In 'auto' mode the rate is fetched once a day from a public source without a key
(RATE_URL, default: Frankfurter, ECB reference rates). The request carries no data of the bar; the response is
untrusted: size-capped, strictly parsed and accepted only within sane bounds. A failure keeps the last rate and
is shown in the UI; nothing else depends on it.
"""

import json
import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSettings

log = logging.getLogger("app.fx")

RATE_MIN, RATE_MAX = Decimal(500), Decimal(5000)  # won per dollar; anything else is a broken answer
MAX_RESPONSE = 64 * 1024
TIMEOUT_S = 8
REFRESH_EVERY = timedelta(hours=24)
RETRY_AFTER_FAILURE = timedelta(hours=1)


class RateError(Exception):
    pass


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Follow at most a couple of redirects, and never away from HTTPS."""

    max_redirections = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not newurl.lower().startswith("https://"):
            raise RateError("redirect away from HTTPS refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url: str) -> bytes:
    if not url.lower().startswith("https://"):
        raise RateError("RATE_URL must be an https:// address")
    opener = urllib.request.build_opener(_HttpsOnlyRedirect)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "bar-inventory"})
    try:
        with opener.open(req, timeout=TIMEOUT_S) as r:
            body = r.read(MAX_RESPONSE + 1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise RateError(f"source unreachable ({type(e).__name__})") from None
    if len(body) > MAX_RESPONSE:
        raise RateError("answer too large")
    return body


def parse_rate(body: bytes) -> tuple[Decimal, str | None]:
    """{"rates": {"KRW": 1400.5}, "date": "2026-11-24"} (Frankfurter; also open.er-api.com) -> (rate, date)."""
    try:
        data = json.loads(body.decode("utf-8"), parse_float=Decimal, parse_int=Decimal)
        rate = data["rates"]["KRW"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raise RateError("unexpected answer") from None
    if not isinstance(rate, Decimal) or not rate.is_finite():
        raise RateError("unexpected answer")
    if not RATE_MIN <= rate <= RATE_MAX:
        raise RateError(f"rate {rate} is outside {RATE_MIN}-{RATE_MAX}")
    day = data.get("date") if isinstance(data.get("date"), str) and len(data.get("date")) <= 10 else None
    return rate.quantize(Decimal("0.0001")), day


# The HTTP call, replaceable in tests (no real network there).
fetch: Callable[[str], bytes] = _http_get


def update_rate(db: Session, *, force: bool = False) -> AppSettings:
    """Fetch and store the rate (auto mode). Keeps the last rate on failure and records the error."""
    s = db.get(AppSettings, 1)
    if s is None or s.rate_mode != "auto":
        return s
    now = db.scalar(select(func.now()))
    if not force:
        fresh = s.rate_updated_at is not None and now - s.rate_updated_at < REFRESH_EVERY and not s.rate_error
        recently_failed = s.rate_error and s.rate_checked_at is not None and now - s.rate_checked_at < RETRY_AFTER_FAILURE
        if fresh or recently_failed:
            return s
    url = get_settings().rate_url
    try:
        rate, day = parse_rate(fetch(url))
    except RateError as e:
        log.warning("exchange rate update failed: %s", e)
        db.execute(update(AppSettings).where(AppSettings.id == 1).values(rate_error=str(e)[:200], rate_checked_at=now))
    else:
        # one row, one statement: safe with several workers updating at once
        db.execute(
            update(AppSettings)
            .where(AppSettings.id == 1, AppSettings.rate_mode == "auto")
            .values(usd_krw_rate=rate, rate_source=_host(url), rate_date=day, rate_updated_at=now, rate_checked_at=now, rate_error=None)
        )
    db.commit()
    db.refresh(s)
    return s


def _host(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0][:64]


# ----------------------------------------------------------------- scheduler
def start_background(session_factory: Callable[[], Session]) -> threading.Event:
    """Check every hour; fetch when the rate is a day old (or an hour after a failure). Returns a stop event."""
    stop = threading.Event()

    def loop() -> None:
        if stop.wait(10):  # let the app start first
            return
        while True:
            try:
                with session_factory() as db:
                    update_rate(db)
            except Exception:  # never let the thread die; the next round retries
                log.exception("exchange rate job failed")
            if stop.wait(3600):
                return

    threading.Thread(target=loop, name="fx-rate", daemon=True).start()
    return stop


def rate_or_none(s: AppSettings) -> Decimal | None:
    try:
        return Decimal(s.usd_krw_rate) if s.usd_krw_rate else None
    except InvalidOperation:
        return None


def is_stale(s: AppSettings, now: datetime) -> bool:
    return s.rate_updated_at is None or now - s.rate_updated_at > 2 * REFRESH_EVERY
