from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.analytics import alerts, kpi
from backend.api.common import parse_day
from backend.auth.deps import require_viewer
from backend.database.session import get_db
from backend.models import JobRun

router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(require_viewer)])


@router.get("/dashboard")
def dashboard(date: str | None = None, days: int = 30, db: Session = Depends(get_db)):
    day = parse_day(date)
    days = min(max(days, 7), 365)
    start = day - timedelta(days=days - 1)
    cats = kpi.codes(db)
    ds = kpi.load(db, start, day)
    period = kpi.summarize(ds, cats)
    last_sync = db.scalar(select(JobRun).where(JobRun.job == "gmail_sync").order_by(JobRun.id.desc()).limit(1))
    return {
        "date": day.isoformat(),
        "period": {"start": start.isoformat(), "end": day.isoformat(), "days": days},
        "today": kpi.day_status(db, day),
        "alerts": alerts.build_alerts(db, day, lookback_days=7),
        "employees": kpi.employee_overview(db, start, day),
        "distribution": period["codes"],
        "period_summary": {k: v for k, v in period.items() if k != "codes"},
        "daily": kpi.daily_series(ds),
        "weekly": kpi.weekly_series(ds, cats),
        "last_sync": {"at": last_sync.started_at.isoformat(), "status": last_sync.status, "message": last_sync.message} if last_sync else None,
    }
