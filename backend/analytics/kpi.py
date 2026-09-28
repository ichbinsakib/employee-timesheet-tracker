"""KPI engine.

Everything here is descriptive: it reports what the timesheets say. There is
deliberately no "productivity score" — timesheets are evidence, not the whole
picture of anyone's performance.

Work is grouped by the company's own costing codes (descriptions from the
"COSTING CODE" sheet in the timesheets), using each row's recorded hours.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import DataQualityIssue, Employee, EntryActivity, Submission, TimesheetEntry
from backend.services import app_settings
from backend.services import costing_codes as cc
from backend.services.employees import expected_on
from backend.services.importer import ACTIVE_STATUSES

# --------------------------------------------------------------------------- data loading
@dataclass
class EntryRow:
    id: int
    employee_id: int
    work_date: date
    hours: float
    completed: bool | None
    features: int | None
    code: str | None


@dataclass
class ActivityRow:
    entry_id: int
    employee_id: int
    work_date: date
    hours: float
    normalized: str
    text: str


@dataclass
class Dataset:
    start: date
    end: date
    entries: list[EntryRow] = field(default_factory=list)  # rows with hours > 0 (counted as tasks)
    activities: list[ActivityRow] = field(default_factory=list)
    # Rows with 0 (or no) hours: standing items listed but not worked that day. Kept out of
    # task counts and averages so they do not inflate "tasks" or shrink "hours per task".
    zero_hour_entries: list[EntryRow] = field(default_factory=list)


def load(db: Session, start: date, end: date, employee_id: int | None = None) -> Dataset:
    ds = Dataset(start, end)
    q = select(
        TimesheetEntry.id, TimesheetEntry.employee_id, TimesheetEntry.work_date, TimesheetEntry.burden_hours,
        TimesheetEntry.completed, TimesheetEntry.feature_count, TimesheetEntry.costing_code,
    ).where(TimesheetEntry.work_date >= start, TimesheetEntry.work_date <= end)
    if employee_id:
        q = q.where(TimesheetEntry.employee_id == employee_id)
    for r in db.execute(q):
        row = EntryRow(r[0], r[1], r[2], float(r[3] or 0), r[4], r[5], (r[6] or "").strip().upper() or None)
        (ds.entries if row.hours > 0 else ds.zero_hour_entries).append(row)

    aq = select(
        EntryActivity.entry_id, TimesheetEntry.employee_id, TimesheetEntry.work_date,
        EntryActivity.allocated_hours, EntryActivity.normalized, EntryActivity.text,
    ).join(TimesheetEntry, TimesheetEntry.id == EntryActivity.entry_id).where(
        TimesheetEntry.work_date >= start, TimesheetEntry.work_date <= end)
    if employee_id:
        aq = aq.where(TimesheetEntry.employee_id == employee_id)
    for r in db.execute(aq):
        if float(r[3] or 0) > 0:  # lines of 0-hour rows are not work done that day
            ds.activities.append(ActivityRow(r[0], r[1], r[2], float(r[3] or 0), r[4], r[5]))
    return ds


def codes(db: Session) -> dict[str, str | None]:
    """Costing code -> description."""
    return cc.descriptions(db)


def _r(x: float | None, n: int = 2) -> float | None:
    return None if x is None else round(x, n)


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


# --------------------------------------------------------------------------- metrics
def code_distribution(ds: Dataset, desc: dict[str, str | None], employee_id: int | None = None) -> list[dict]:
    """Hours per costing code (recorded hours, not estimates)."""
    hours: dict[str | None, float] = defaultdict(float)
    tasks: Counter = Counter()
    for e in ds.entries:
        if employee_id is None or e.employee_id == employee_id:
            hours[e.code] += e.hours
            tasks[e.code] += 1
    total = sum(hours.values())
    return [
        {"code": code or cc.NO_CODE, "description": desc.get(code) if code else "No costing code on the row",
         "label": cc.label(code, desc), "in_list": bool(code and code in getattr(desc, "listed", desc)),
         "hours": _r(h), "tasks": tasks[code], "percent": _pct(h, total)}
        for code, h in sorted(hours.items(), key=lambda kv: -kv[1])
    ]


def summarize(ds: Dataset, desc: dict[str, str | None], employee_id: int | None = None) -> dict:
    entries = [e for e in ds.entries if employee_id is None or e.employee_id == employee_id]
    total_hours = sum(e.hours for e in entries)
    days = sorted({(e.employee_id, e.work_date) for e in entries})
    completed = sum(1 for e in entries if e.completed is True)
    incomplete = sum(1 for e in entries if e.completed is False)
    feat_entries = [e for e in entries if e.features is not None]
    feat_total = sum(e.features or 0 for e in feat_entries)
    feat_hours = sum(e.hours for e in feat_entries)
    acts = [a for a in ds.activities if employee_id is None or a.employee_id == employee_id]
    dist = code_distribution(ds, desc, employee_id)
    return {
        "total_hours": _r(total_hours),
        "days_submitted": len(days),
        "avg_daily_hours": _r(total_hours / len(days)) if days else None,
        "task_count": len(entries),
        "zero_hour_rows": sum(1 for e in ds.zero_hour_entries if employee_id is None or e.employee_id == employee_id),
        "activity_count": len(acts),
        "completed_tasks": completed,
        "incomplete_tasks": incomplete,
        "completion_not_recorded": len(entries) - completed - incomplete,
        "completion_rate": _pct(completed, completed + incomplete),
        "avg_hours_per_task": _r(total_hours / len(entries)) if entries else None,
        "feature_tasks": len(feat_entries),
        "feature_total": feat_total,
        "feature_hours": _r(feat_hours),
        "hours_per_feature": _r(feat_hours / feat_total) if feat_total else None,
        "codes_used": len(dist),
        "codes": dist,
    }


def daily_series(ds: Dataset, employee_id: int | None = None) -> list[dict]:
    by_day: dict[date, dict] = {}
    d = ds.start
    while d <= ds.end:
        by_day[d] = {"date": d.isoformat(), "hours": 0.0, "tasks": 0, "completed": 0, "incomplete": 0, "employees": set()}
        d += timedelta(days=1)
    for e in ds.entries:
        if employee_id is not None and e.employee_id != employee_id:
            continue
        row = by_day.get(e.work_date)
        if row is None:
            continue
        row["hours"] += e.hours
        row["tasks"] += 1
        row["completed"] += e.completed is True
        row["incomplete"] += e.completed is False
        row["employees"].add(e.employee_id)
    out = []
    for row in by_day.values():
        row["hours"] = round(row["hours"], 2)
        row["employees"] = len(row["employees"])
        out.append(row)
    return out


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_series(ds: Dataset, desc: dict[str, str | None], employee_id: int | None = None) -> list[dict]:
    weeks: dict[date, dict] = {}
    w = week_start(ds.start)
    while w <= ds.end:
        weeks[w] = {"week": w.isoformat(), "hours": 0.0, "tasks": 0, "completed": 0, "incomplete": 0, "codes": defaultdict(float)}
        w += timedelta(days=7)
    for e in ds.entries:
        if employee_id is not None and e.employee_id != employee_id:
            continue
        row = weeks.get(week_start(e.work_date))
        if row:
            row["hours"] += e.hours
            row["tasks"] += 1
            row["completed"] += e.completed is True
            row["incomplete"] += e.completed is False
            row["codes"][e.code or cc.NO_CODE] += e.hours
    out = []
    for row in weeks.values():
        total = sum(row["codes"].values())
        row["code_pct"] = {k: _pct(v, total) for k, v in row["codes"].items()}
        row["codes"] = {k: round(v, 2) for k, v in row["codes"].items()}
        row["hours"] = round(row["hours"], 2)
        row["completion_rate"] = _pct(row["completed"], row["completed"] + row["incomplete"])
        out.append(row)
    return out


def repeated_activities(ds: Dataset, employee_id: int | None = None, limit: int = 15) -> list[dict]:
    """Activity lines that recur on two or more days (same wording, normalised)."""
    groups: dict[str, dict] = {}
    for a in ds.activities:
        if (employee_id is not None and a.employee_id != employee_id) or not a.normalized:
            continue
        g = groups.setdefault(a.normalized, {"activity": a.text, "days": set(), "employees": set(), "count": 0, "hours": 0.0})
        g["days"].add(a.work_date)
        g["employees"].add(a.employee_id)
        g["count"] += 1
        g["hours"] += a.hours
    rows = [
        {"activity": g["activity"], "days": len(g["days"]), "occurrences": g["count"],
         "employees": len(g["employees"]), "est_hours": round(g["hours"], 2)}
        for g in groups.values() if len(g["days"]) >= 2
    ]
    rows.sort(key=lambda r: (-r["days"], -r["est_hours"]))
    return rows[:limit]


# --------------------------------------------------------------------------- submission coverage
def submitted_days(db: Session, start: date, end: date) -> set[tuple[int, date]]:
    q = select(Submission.employee_id, Submission.work_date).where(
        Submission.work_date >= start, Submission.work_date <= end,
        Submission.import_status.in_(ACTIVE_STATUSES), Submission.employee_id.is_not(None))
    return {(r[0], r[1]) for r in db.execute(q)}


def _deadline_passed(emp: Employee, day: date, now: datetime) -> bool:
    if day < now.date():
        return True
    if day > now.date():
        return False
    try:
        hh, mm = (int(x) for x in (emp.submission_deadline or "18:00").split(":"))
    except ValueError:
        hh, mm = 18, 0
    return (now.hour, now.minute) >= (hh, mm)


def missing_timesheets(db: Session, start: date, end: date, employee_id: int | None = None, now: datetime | None = None) -> list[dict]:
    """Expected working days with no imported timesheet. Today counts only after the deadline."""
    now = now or datetime.now()
    end = min(end, now.date())
    holidays = app_settings.holidays(db)
    have = submitted_days(db, start, end)
    q = select(Employee).where(Employee.active.is_(True))
    if employee_id:
        q = q.where(Employee.id == employee_id)
    out = []
    for emp in db.scalars(q):
        d = start
        while d <= end:
            if expected_on(emp, d, holidays) and (emp.id, d) not in have and _deadline_passed(emp, d, now):
                out.append({"employee_id": emp.id, "employee": emp.name, "date": d.isoformat()})
            d += timedelta(days=1)
    out.sort(key=lambda r: (r["date"], r["employee"]), reverse=True)
    return out


def data_quality(db: Session, start: date, end: date, employee_id: int | None = None, min_severity: str = "warning") -> list[dict]:
    severities = ["error"] if min_severity == "error" else ["warning", "error"] if min_severity == "warning" else ["info", "warning", "error"]
    q = (select(DataQualityIssue, Submission, Employee)
         .join(Submission, Submission.id == DataQualityIssue.submission_id)
         .outerjoin(Employee, Employee.id == DataQualityIssue.employee_id)
         .where(Submission.import_status.not_in(("superseded", "duplicate")),
                DataQualityIssue.severity.in_(severities))
         .order_by(DataQualityIssue.id.desc()))
    q = q.where((DataQualityIssue.work_date.is_(None)) | ((DataQualityIssue.work_date >= start) & (DataQualityIssue.work_date <= end)))
    if employee_id:
        q = q.where(DataQualityIssue.employee_id == employee_id)
    return [
        {"id": i.id, "submission_id": s.id, "employee_id": i.employee_id, "employee": e.name if e else None,
         "date": i.work_date.isoformat() if i.work_date else None, "severity": i.severity, "code": i.code,
         "message": i.message, "excel_row": i.excel_row, "file": s.attachment_filename}
        for i, s, e in db.execute(q.limit(500))
    ]


# --------------------------------------------------------------------------- baselines & anomalies
def baseline(db: Session, desc: dict[str, str | None], start: date, end: date, employee_id: int | None = None) -> dict:
    """Same-length period immediately before [start, end]."""
    length = (end - start).days + 1
    b_end = start - timedelta(days=1)
    b_start = b_end - timedelta(days=length - 1)
    ds = load(db, b_start, b_end, employee_id)
    out = summarize(ds, desc, employee_id)
    out["start"], out["end"] = b_start.isoformat(), b_end.isoformat()
    return out


def compare(current: dict, base: dict) -> list[dict]:
    """Factual changes between two summaries."""
    rows = []
    for key, label, unit in [
        ("avg_daily_hours", "Average daily hours", "h"), ("task_count", "Tasks", ""),
        ("completion_rate", "Completion rate", "%"), ("avg_hours_per_task", "Average hours per task", "h"),
        ("codes_used", "Costing codes worked on", ""),
    ]:
        cur, prev = current.get(key), base.get(key)
        change = round(cur - prev, 2) if isinstance(cur, (int, float)) and isinstance(prev, (int, float)) else None
        rows.append({"metric": label, "key": key, "current": cur, "previous": prev, "change": change, "unit": unit})
    return rows


def daily_hours_anomalies(db: Session, start: date, end: date, employee_id: int | None = None) -> list[dict]:
    """Days where recorded hours differ markedly from the employee's recent history."""
    threshold = app_settings.get_float(db, "unusual_hours_threshold", 12.0)
    hist = load(db, start - timedelta(days=90), end, employee_id)
    per_emp: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for e in hist.entries:
        per_emp[e.employee_id][e.work_date] += e.hours
    names = {e.id: e.name for e in db.scalars(select(Employee))}
    out = []
    for emp_id, days in per_emp.items():
        ordered = sorted(days)
        for i, d in enumerate(ordered):
            if d < start or d > end:
                continue
            prior = [days[x] for x in ordered[max(0, i - 20):i]]
            hours = days[d]
            avg = statistics.mean(prior) if prior else None
            reason = None
            if len(prior) >= 5:
                sd = statistics.pstdev(prior)
                if abs(hours - avg) >= max(2 * sd, 2.0):
                    reason = "differs from recent average"
            if hours >= threshold:
                reason = reason or f"at or above {threshold:g} hours"
            if hours == 0:
                reason = "no hours recorded"
            if reason:
                out.append({"employee_id": emp_id, "employee": names.get(emp_id), "date": d.isoformat(),
                            "hours": round(hours, 2), "recent_average": _r(avg), "samples": len(prior), "reason": reason})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def code_shifts(current: dict, base: dict, min_points: float = 15.0, min_base_hours: float = 8.0) -> list[dict]:
    """Costing codes whose share of hours moved by at least `min_points` percentage points."""
    if (base.get("total_hours") or 0) < min_base_hours or (current.get("total_hours") or 0) < min_base_hours:
        return []
    prev = {c["code"]: c for c in base["codes"]}
    cur = {c["code"]: c for c in current["codes"]}
    out = []
    for code in set(prev) | set(cur):
        p = (prev.get(code) or {}).get("percent") or 0
        c = (cur.get(code) or {}).get("percent") or 0
        if abs(c - p) >= min_points:
            lbl = (cur.get(code) or prev.get(code))["label"]
            out.append({"code": code, "label": lbl, "previous_pct": p, "current_pct": c, "change": round(c - p, 1)})
    out.sort(key=lambda r: -abs(r["change"]))
    return out


# --------------------------------------------------------------------------- composed views
def employee_overview(db: Session, start: date, end: date) -> list[dict]:
    desc = codes(db)
    ds = load(db, start, end)
    missing = Counter(m["employee_id"] for m in missing_timesheets(db, start, end))
    rows = []
    for emp in db.scalars(select(Employee).order_by(Employee.name)):
        s = summarize(ds, desc, emp.id)
        if not emp.active and not s["task_count"]:
            continue
        top = s["codes"][0]["label"] if s["codes"] else None
        rows.append({
            "employee_id": emp.id, "employee": emp.name, "department": emp.department, "active": emp.active,
            "hours": s["total_hours"], "days_submitted": s["days_submitted"], "avg_daily_hours": s["avg_daily_hours"],
            "tasks": s["task_count"], "completed": s["completed_tasks"], "incomplete": s["incomplete_tasks"],
            "completion_rate": s["completion_rate"], "avg_hours_per_task": s["avg_hours_per_task"],
            "missing_days": missing.get(emp.id, 0), "top_code": top,
        })
    return rows


def day_status(db: Session, day: date, now: datetime | None = None) -> dict:
    """The dashboard's "Today" block for any given day."""
    now = now or datetime.now()
    holidays = app_settings.holidays(db)
    have = {emp for emp, d in submitted_days(db, day, day)}
    employees = list(db.scalars(select(Employee).where(Employee.active.is_(True)).order_by(Employee.name)))
    expected = [e for e in employees if expected_on(e, day, holidays)]
    missing, pending = [], []
    for e in expected:
        if e.id in have:
            continue
        (missing if _deadline_passed(e, day, now) else pending).append({"employee_id": e.id, "employee": e.name, "deadline": e.submission_deadline})
    ds = load(db, day, day)
    s = summarize(ds, codes(db))
    return {
        "date": day.isoformat(), "is_holiday": day in holidays,
        "expected": len(expected), "submitted": len(have), "missing": missing, "pending": pending,
        "total_hours": s["total_hours"], "tasks": s["task_count"],
        "completed": s["completed_tasks"], "incomplete": s["incomplete_tasks"],
        "completion_not_recorded": s["completion_not_recorded"],
    }
