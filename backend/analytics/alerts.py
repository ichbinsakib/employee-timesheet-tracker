"""Management alerts.

Every alert states a fact and where it came from. Alerts never judge people
("unproductive", "performed poorly"); they point at something worth a look.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.analytics import kpi
from backend.models import Employee, JobRun, Submission

INCOMPLETE_ALERT_MIN = 5


def build_alerts(db: Session, day: date, lookback_days: int = 7, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    start = day - timedelta(days=lookback_days - 1)
    alerts: list[dict] = []
    cats = kpi.codes(db)

    # Missing timesheets
    for m in kpi.missing_timesheets(db, start, day, now=now):
        if m["date"] == now.date().isoformat():
            msg = f"{m['employee']} has not submitted today's timesheet."
        else:
            msg = f"{m['employee']} has not submitted a timesheet for {date.fromisoformat(m['date']):%a %d %b}."
        alerts.append(_a("missing", "warning", "Missing timesheet", msg, m["employee_id"], m["date"]))

    # Unusual hours
    for a in kpi.daily_hours_anomalies(db, start, day):
        if a["reason"] == "no hours recorded":
            msg = f"{a['employee']} submitted a timesheet with no hours on {a['date']}."
        elif a["recent_average"] is not None:
            msg = f"{a['employee']} recorded {a['hours']:g} hours on {a['date']}. Recent average: {a['recent_average']:g} hours."
        else:
            msg = f"{a['employee']} recorded {a['hours']:g} hours on {a['date']}."
        alerts.append(_a("unusual_hours", "info", "Unusual hours", msg, a["employee_id"], a["date"]))

    # Costing-code change and incomplete work, per employee (period vs previous period of same length)
    ds = kpi.load(db, start, day)
    for emp in db.scalars(select(Employee).where(Employee.active.is_(True))):
        cur = kpi.summarize(ds, cats, emp.id)
        if not cur["task_count"]:
            continue
        base = kpi.baseline(db, cats, start, day, emp.id)
        for shift in kpi.code_shifts(cur, base)[:2]:
            direction = "increased" if shift["change"] > 0 else "decreased"
            alerts.append(_a("code_change", "info", "Costing code change",
                             f"{emp.name}: share of hours on {shift['label']} {direction} from {shift['previous_pct']:g}% to {shift['current_pct']:g}% "
                             f"(last {lookback_days} days vs the {lookback_days} days before).", emp.id, None))
        if cur["incomplete_tasks"] >= INCOMPLETE_ALERT_MIN:
            alerts.append(_a("incomplete", "info", "Incomplete work",
                             f"{emp.name} has {cur['incomplete_tasks']} tasks recorded as not completed in the last {lookback_days} days.",
                             emp.id, None))
        if emp.auto_created and not emp.department:
            alerts.append(_a("new_employee", "info", "New employee added",
                             f"{emp.name} was added automatically from a timesheet. Check their email, department and working days.",
                             emp.id, None))

    # Import problems
    since = datetime.combine(start, datetime.min.time())
    failed = db.scalars(select(Submission).where(Submission.import_status == "failed", Submission.import_timestamp >= since)
                        .order_by(Submission.id.desc()).limit(10))
    for s in failed:
        who = s.sender_email or "an upload"
        alerts.append(_a("import_failed", "warning", "Timesheet could not be imported",
                         f"'{s.attachment_filename}' from {who}: {s.error_message}", s.employee_id,
                         s.work_date.isoformat() if s.work_date else None, submission_id=s.id))
    errors = [q for q in kpi.data_quality(db, start, day, min_severity="error") if q["code"] != "import_failed"]
    if errors:
        alerts.append(_a("data_quality", "warning", "Data quality",
                         f"{len(errors)} data error(s) in timesheets from the last {lookback_days} days. See Imports for details.", None, None))

    # Gmail sync health
    last_sync = db.scalar(select(JobRun).where(JobRun.job == "gmail_sync").order_by(JobRun.id.desc()).limit(1))
    if last_sync and last_sync.status == "error":
        alerts.append(_a("gmail", "warning", "Gmail sync problem", f"Last sync at {last_sync.started_at:%d %b %H:%M}: {last_sync.message}", None, None))
    elif last_sync is None:
        alerts.append(_a("gmail", "info", "Gmail sync has not run", "No Gmail sync has run yet. Connect Gmail and press Sync Gmail Now.", None, None))

    order = {"warning": 0, "info": 1}
    alerts.sort(key=lambda a: (order.get(a["severity"], 2), a["date"] or "9999"), reverse=False)
    return alerts


def _a(kind: str, severity: str, title: str, message: str, employee_id: int | None, day: str | None, **extra) -> dict:
    return {"type": kind, "severity": severity, "title": title, "message": message,
            "employee_id": employee_id, "date": day, **extra}
