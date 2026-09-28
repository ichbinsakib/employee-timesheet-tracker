"""Background jobs, running inside the server process.

They keep running whether or not any browser is open. On startup the app
catches up: it syncs Gmail (looking back N days), takes a backup if the last one
is overdue, and generates any daily report that was missed while the PC was off.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select

from backend.config import settings
from backend.database.session import session_scope
from backend.models import AccessLog, AuthSession, GeneratedReport, now
from backend.services import app_settings
from backend.services import backup as backup_svc
from backend.services.jobs import record_job

log = logging.getLogger(__name__)
scheduler: BackgroundScheduler | None = None


# --------------------------------------------------------------------------- job bodies
def job_gmail_sync(trigger: str = "schedule") -> dict:
    from backend.gmail.sync import sync_gmail
    return sync_gmail(trigger)


def job_backup(trigger: str = "schedule") -> str:
    with record_job("backup", trigger) as job:
        path = backup_svc.create_backup("manual" if trigger == "manual" else "")
        with session_scope() as db:
            retain = app_settings.get_int(db, "backup_retention", 30)
        removed = backup_svc.prune_backups(retain)
        job.message = f"Saved {path.name}" + (f"; removed {removed} old backup(s)" if removed else "")
        return path.name


def job_daily_report(trigger: str = "schedule", day: date | None = None) -> list[str]:
    from backend.reports.daily import generate_and_save
    day = day or date.today()
    with record_job("daily_report", trigger) as job:
        with session_scope() as db:
            paths = generate_and_save(db, day)
        job.message = f"Report for {day.isoformat()}: " + ", ".join(p.name for p in paths)
        return [str(p) for p in paths]


def job_cleanup() -> None:
    with session_scope() as db:
        db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
        db.execute(delete(AccessLog).where(AccessLog.ts < now() - timedelta(days=180)))


def _report_time(db) -> tuple[int, int]:
    try:
        hh, mm = (int(x) for x in app_settings.get(db, "daily_report_time").split(":"))
        return hh, mm
    except ValueError:
        return 19, 0


def catch_up() -> None:
    """Run whatever was missed while the desktop/application was off."""
    try:
        job_gmail_sync("startup")
    except Exception:  # noqa: BLE001
        log.exception("Startup Gmail sync failed")
    try:
        with session_scope() as db:
            hours = app_settings.get_int(db, "backup_interval_hours", 24)
        latest = backup_svc.list_backups()
        latest_auto = next((b for b in latest if b["kind"] != "pre-restore"), None)
        if settings.database_path.exists() and (latest_auto is None or datetime.fromisoformat(latest_auto["modified"]) < datetime.now() - timedelta(hours=hours)):
            job_backup("startup")
    except Exception:  # noqa: BLE001
        log.exception("Startup backup failed")
    try:
        with session_scope() as db:
            hh, mm = _report_time(db)
            have = set(db.scalars(select(GeneratedReport.report_date).where(GeneratedReport.report_date >= date.today() - timedelta(days=3))))
        now_dt = datetime.now()
        for back in range(3, -1, -1):
            d = date.today() - timedelta(days=back)
            due = datetime.combine(d, datetime.min.time()).replace(hour=hh, minute=mm)
            if d not in have and now_dt >= due:
                job_daily_report("startup", d)
    except Exception:  # noqa: BLE001
        log.exception("Startup report catch-up failed")


# --------------------------------------------------------------------------- scheduler control
def mark_interrupted_jobs() -> None:
    """Jobs still 'running' from a previous process were cut off when the app stopped."""
    from backend.models import JobRun
    with session_scope() as db:
        for run in db.scalars(select(JobRun).where(JobRun.status == "running")):
            run.status, run.finished_at = "error", now()
            run.message = "Interrupted: the app stopped while this was running."


def start() -> None:
    global scheduler
    if scheduler is not None:
        return
    mark_interrupted_jobs()
    scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    scheduler.start()
    reschedule()
    scheduler.add_job(catch_up, id="catch_up", next_run_time=datetime.now() + timedelta(seconds=10))
    scheduler.add_job(job_cleanup, CronTrigger(hour=3, minute=30), id="cleanup", replace_existing=True)
    log.info("Scheduler started")


def reschedule() -> None:
    """Apply interval/time settings. Called at start and when settings change."""
    if scheduler is None:
        return
    with session_scope() as db:
        sync_min = max(app_settings.get_int(db, "sync_interval_minutes", 15), 1)
        backup_h = max(app_settings.get_int(db, "backup_interval_hours", 24), 1)
        hh, mm = _report_time(db)
    scheduler.add_job(job_gmail_sync, IntervalTrigger(minutes=sync_min), id="gmail_sync", replace_existing=True)
    scheduler.add_job(job_backup, IntervalTrigger(hours=backup_h), id="backup", replace_existing=True)
    scheduler.add_job(job_daily_report, CronTrigger(hour=hh, minute=mm), id="daily_report", replace_existing=True)


def shutdown() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None


def next_runs() -> dict:
    if scheduler is None:
        return {}
    out = {}
    for job in scheduler.get_jobs():
        out[job.id] = job.next_run_time.isoformat(timespec="seconds") if job.next_run_time else None
    return out
