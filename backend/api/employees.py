from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.analytics import kpi
from backend.api.common import parse_range
from backend.auth.deps import require_manager, require_viewer
from backend.database.session import get_db
from backend.models import Employee, TimesheetEntry, WorkCategory

router = APIRouter(prefix="/api/employees", tags=["employees"])


class EmployeeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: str = ""
    email: str | None = None
    department: str | None = None
    job_title: str | None = None
    expected_daily_hours: float = Field(8.0, ge=0, le=24)
    expected_weekly_hours: float = Field(40.0, ge=0, le=168)
    working_days: str = "Mon,Tue,Wed,Thu,Fri"
    submission_deadline: str = "18:00"
    tracking_start: date | None = None
    active: bool = True

    @field_validator("submission_deadline")
    @classmethod
    def _deadline(cls, v: str) -> str:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("Use HH:MM (24-hour), e.g. 18:00")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("Not a valid email address")
        return v or None


def employee_out(e: Employee) -> dict:
    return {
        "id": e.id, "name": e.name, "aliases": e.aliases, "email": e.email, "department": e.department,
        "job_title": e.job_title, "expected_daily_hours": e.expected_daily_hours,
        "expected_weekly_hours": e.expected_weekly_hours, "working_days": e.working_days,
        "submission_deadline": e.submission_deadline,
        "tracking_start": e.tracking_start.isoformat() if e.tracking_start else None,
        "active": e.active, "auto_created": e.auto_created, "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("", dependencies=[Depends(require_viewer)])
def list_employees(include_inactive: bool = True, db: Session = Depends(get_db)):
    q = select(Employee).order_by(Employee.active.desc(), Employee.name)
    if not include_inactive:
        q = q.where(Employee.active.is_(True))
    return [employee_out(e) for e in db.scalars(q)]


@router.post("", dependencies=[Depends(require_manager)])
def create_employee(body: EmployeeIn, db: Session = Depends(get_db)):
    e = Employee(**body.model_dump())
    e.tracking_start = e.tracking_start or date.today()
    db.add(e)
    db.commit()
    return employee_out(e)


@router.put("/{employee_id}", dependencies=[Depends(require_manager)])
def update_employee(employee_id: int, body: EmployeeIn, db: Session = Depends(get_db)):
    e = db.get(Employee, employee_id)
    if e is None:
        raise HTTPException(404, "Employee not found")
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    e.auto_created = False  # reviewed by a person
    db.commit()
    return employee_out(e)


@router.get("/{employee_id}", dependencies=[Depends(require_viewer)])
def employee_detail(employee_id: int, start: str | None = None, end: str | None = None, days: int = 30,
                    db: Session = Depends(get_db)):
    e = db.get(Employee, employee_id)
    if e is None:
        raise HTTPException(404, "Employee not found")
    s, t = parse_range(start, end, days)
    cats = kpi.categories(db)
    ds = kpi.load(db, s, t, e.id)
    summary = kpi.summarize(ds, cats, e.id)
    base = kpi.baseline(db, cats, s, t, e.id)
    recent = db.execute(
        select(TimesheetEntry, WorkCategory.name).outerjoin(WorkCategory, WorkCategory.id == TimesheetEntry.primary_category_id)
        .where(TimesheetEntry.employee_id == e.id).order_by(TimesheetEntry.work_date.desc(), TimesheetEntry.original_excel_row).limit(50)
    ).all()
    return {
        "employee": employee_out(e),
        "period": {"start": s.isoformat(), "end": t.isoformat()},
        "summary": {k: v for k, v in summary.items() if k != "categories"},
        "categories": summary["categories"],
        "daily": kpi.daily_series(ds, e.id),
        "weekly": kpi.weekly_series(ds, cats, e.id),
        "comparison": {"previous_period": {"start": base["start"], "end": base["end"]}, "rows": kpi.compare(summary, base)},
        "category_shifts": kpi.category_shifts(summary, base),
        "anomalies": kpi.daily_hours_anomalies(db, s, t, e.id),
        "missing": kpi.missing_timesheets(db, s, t, e.id),
        "data_quality": kpi.data_quality(db, s, t, e.id, min_severity="info"),
        "repeated": kpi.repeated_activities(ds, e.id, limit=10),
        "recent_entries": [entry_out(x, cat) for x, cat in recent],
    }


def entry_out(x: TimesheetEntry, category: str | None) -> dict:
    return {
        "id": x.id, "submission_id": x.submission_id, "employee_id": x.employee_id, "date": x.work_date.isoformat(),
        "costing_code": x.costing_code, "title": x.title, "notes": x.notes, "file_type": x.file_type,
        "completed": x.completed, "completed_raw": x.completed_raw, "features": x.feature_count,
        "hours": x.burden_hours, "excel_row": x.original_excel_row, "category": category,
    }
