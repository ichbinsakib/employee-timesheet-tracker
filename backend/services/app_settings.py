"""Runtime settings stored in the database (editable from the Settings page)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from backend.database.init_db import DEFAULT_APP_SETTINGS
from backend.models import AppSetting


def get(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else DEFAULT_APP_SETTINGS.get(key, "")


def get_int(db: Session, key: str, fallback: int) -> int:
    try:
        return int(float(get(db, key)))
    except (TypeError, ValueError):
        return fallback


def get_float(db: Session, key: str, fallback: float) -> float:
    try:
        return float(get(db, key))
    except (TypeError, ValueError):
        return fallback


def set_value(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def all_settings(db: Session) -> dict[str, str]:
    out = dict(DEFAULT_APP_SETTINGS)
    for row in db.query(AppSetting).all():
        out[row.key] = row.value
    return out


def holidays(db: Session) -> set[date]:
    out: set[date] = set()
    for part in get(db, "holidays").replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.add(date.fromisoformat(part))
            except ValueError:
                pass
    return out
