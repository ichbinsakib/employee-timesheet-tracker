from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.analytics import kpi
from backend.api.common import parse_range
from backend.auth.deps import require_viewer
from backend.database.session import get_db

router = APIRouter(prefix="/api", tags=["analytics"], dependencies=[Depends(require_viewer)])


@router.get("/analytics")
def analytics(start: str | None = None, end: str | None = None, days: int = 30, employee_id: int | None = None,
              db: Session = Depends(get_db)):
    s, t = parse_range(start, end, days)
    cats = kpi.codes(db)
    ds = kpi.load(db, s, t, employee_id)
    summary = kpi.summarize(ds, cats, employee_id)
    base = kpi.baseline(db, cats, s, t, employee_id)
    return {
        "period": {"start": s.isoformat(), "end": t.isoformat()},
        "summary": {k: v for k, v in summary.items() if k != "codes"},
        "codes": summary["codes"],
        "daily": kpi.daily_series(ds, employee_id),
        "weekly": kpi.weekly_series(ds, cats, employee_id),
        "comparison": {"previous_period": {"start": base["start"], "end": base["end"]}, "rows": kpi.compare(summary, base)},
        "code_shifts": kpi.code_shifts(summary, base),
        "repeated": kpi.repeated_activities(ds, employee_id),
        "anomalies": kpi.daily_hours_anomalies(db, s, t, employee_id),
        "missing": kpi.missing_timesheets(db, s, t, employee_id),
        "data_quality": kpi.data_quality(db, s, t, employee_id),
        "employees": [] if employee_id else kpi.employee_overview(db, s, t),
    }
