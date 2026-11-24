from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DbSession, require
from app.api.v1.auth import user_out
from app.core.permissions import Perm
from app.core.security import hash_password
from app.models import Role, User
from app.schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])
Admin = Annotated[User, Depends(require(Perm.manage_users))]


@router.get("", response_model=list[UserOut])
def list_users(_: Admin, db: DbSession) -> list[UserOut]:
    return [user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, _: Admin, db: DbSession) -> UserOut:
    if db.scalar(select(User).where(func.lower(User.username) == body.username.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    user = User(
        username=body.username,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
        token_version=0,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # concurrent creation of the same username
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists") from None
    return user_out(user)


def _lock_active_admins(db: Session) -> list[User]:
    # Lock all active admins so two concurrent demotions cannot both pass the "last admin" check.
    return list(
        db.scalars(
            select(User).where(User.role == Role.admin, User.is_active).order_by(User.id).with_for_update()
        )
    )


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, admin: Admin, db: DbSession) -> UserOut:
    active_admins = _lock_active_admins(db)
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    loses_admin = user.role == Role.admin and user.is_active and (
        (body.role is not None and body.role != Role.admin) or body.is_active is False
    )
    if body.password is not None and user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use /auth/change-password to change your own password")
    if loses_admin and user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot deactivate or demote yourself")
    if loses_admin and len(active_admins) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last active administrator")

    revoke = False
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None and body.role != user.role:
        user.role = body.role
        revoke = True
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        revoke = True
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        revoke = True
    if revoke:
        user.token_version += 1
    db.commit()
    return user_out(user)
