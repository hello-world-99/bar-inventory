from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.permissions import ROLE_PERMISSIONS
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import create_token, decode_token, hash_password, needs_rehash, verify_password
from app.models import User
from app.schemas import LoginIn, PasswordChange, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
REFRESH_PATH = "/api/v1/auth"

_settings = get_settings()
# The client IP comes from uvicorn's proxy-header handling; nginx overwrites X-Forwarded-For
# with $remote_addr, so a client cannot choose its own key here.
login_limiter = SlidingWindowLimiter(_settings.login_max_attempts, _settings.login_window_seconds)
user_login_limiter = SlidingWindowLimiter(_settings.login_user_max_attempts, _settings.login_user_window_seconds)


def user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.permissions = sorted(p.value for p in ROLE_PERMISSIONS[user.role])
    return out


def _clear_refresh(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)


def _issue(response: Response, user: User) -> TokenOut:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        create_token(user.id, user.token_version, "refresh"),
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path=REFRESH_PATH,
    )
    return TokenOut(
        access_token=create_token(user.id, user.token_version, "access"),
        expires_in=s.access_token_minutes * 60,
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> TokenOut:
    ip = request.client.host if request.client else "unknown"
    uname = body.username.lower()
    key = f"{ip}|{uname}"
    if login_limiter.is_blocked(key) or user_login_limiter.is_blocked(uname):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts, try again later")
    user = db.scalar(select(User).where(func.lower(User.username) == uname))
    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        login_limiter.hit(key)
        user_login_limiter.hit(uname)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    login_limiter.reset(key)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()
    return _issue(response, user)


@router.post("/refresh", response_model=TokenOut)
def refresh(response: Response, db: DbSession, refresh_token: str | None = Cookie(default=None)) -> TokenOut:
    payload = decode_token(refresh_token, "refresh") if refresh_token else None
    user = db.get(User, int(payload["sub"])) if payload else None
    if payload is None or user is None or not user.is_active or user.token_version != payload.get("tv"):
        _clear_refresh(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    return _issue(response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    _clear_refresh(response)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(user: CurrentUser, response: Response, db: DbSession) -> None:
    user.token_version += 1
    db.commit()
    _clear_refresh(response)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.post("/change-password", response_model=TokenOut)
def change_password(body: PasswordChange, user: CurrentUser, response: Response, db: DbSession) -> TokenOut:
    key = f"pw:{user.id}"
    if login_limiter.is_blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try again later")
    if not verify_password(body.current_password, user.password_hash):
        login_limiter.hit(key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    login_limiter.reset(key)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # signs out other devices
    db.commit()
    return _issue(response, user)  # keep the current device signed in
