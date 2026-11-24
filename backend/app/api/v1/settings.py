from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, require
from app.core.permissions import Perm
from app.models import AppSettings, User
from app.schemas import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def load_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:  # created by the initial migration; recreate defensively
        row = AppSettings(id=1)
        db.add(row)
        db.flush()
    return row


@router.get("", response_model=SettingsOut)
def get_app_settings(_: CurrentUser, db: DbSession) -> AppSettings:
    return load_settings(db)


@router.patch("", response_model=SettingsOut)
def update_app_settings(
    body: SettingsUpdate, _: Annotated[User, Depends(require(Perm.manage_settings))], db: DbSession
) -> AppSettings:
    row = load_settings(db)
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(row, field, value)
    db.commit()
    return row
