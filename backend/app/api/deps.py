from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.permissions import Perm, has_perm
from app.core.security import decode_token
from app.db import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    payload = decode_token(creds.credentials, "access")
    if payload is None:
        raise unauthorized
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active or user.token_version != payload.get("tv"):
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(perm: Perm) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        if not has_perm(user.role, perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker
