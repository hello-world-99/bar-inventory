from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, require
from app.core.permissions import Perm
from app.models import AppSettings, User
from app.schemas import SettingsOut, SettingsUpdate
from app.services import fx

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


DECIMALS = {"KRW": 0, "USD": 2}
Admin = Annotated[User, Depends(require(Perm.manage_settings))]


@router.patch("", response_model=SettingsOut)
def update_app_settings(body: SettingsUpdate, _: Admin, db: DbSession) -> AppSettings:
    row = load_settings(db)
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    rate = data.pop("usd_krw_rate", None)
    for field, value in data.items():
        setattr(row, field, value)
    if rate is not None:
        if row.rate_mode != "manual":
            raise HTTPException(422, {"code": "rate_is_automatic", "message": "Switch the rate to manual to type it in"})
        row.usd_krw_rate, row.rate_source, row.rate_date, row.rate_error = rate, "manual", None, None
        row.rate_updated_at = row.rate_checked_at = func.now()
    row.currency_decimals = DECIMALS[row.currency]
    if row.currency == "USD" and not row.usd_krw_rate:
        db.rollback()
        raise HTTPException(422, {"code": "rate_required", "message": "There is no USD rate yet: update it or type it in first"})
    db.commit()
    db.refresh(row)
    if data.get("rate_mode") == "auto":
        fx.update_rate(db, force=True)
    return row


@router.post("/rate/update", response_model=SettingsOut)
def update_rate_now(_: Admin, db: DbSession) -> AppSettings:
    """Fetch the rate now (auto mode). A failure keeps the last rate; it is reported in rate_error, not as an error."""
    row = load_settings(db)
    if row.rate_mode != "auto":
        raise HTTPException(422, {"code": "rate_is_manual", "message": "The rate is typed in manually; switch to automatic first"})
    return fx.update_rate(db, force=True)
