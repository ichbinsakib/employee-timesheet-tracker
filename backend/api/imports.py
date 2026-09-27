from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.auth.deps import require_admin, require_manager, require_viewer
from backend.config import settings
from backend.database.session import get_db
from backend.gmail import client as gmail_client
from backend.models import DataQualityIssue, Employee, GmailMessage, JobRun, Submission
from backend.services.importer import ImportContext, import_file, sha256, store_file
from backend.services.scheduler import job_gmail_sync, next_runs

router = APIRouter(prefix="/api/imports", tags=["imports"])
MAX_UPLOAD = 15 * 1024 * 1024


def submission_out(s: Submission, emp_name: str | None) -> dict:
    return {
        "id": s.id, "employee_id": s.employee_id, "employee": emp_name, "source": s.source,
        "sender": s.sender_email, "subject": s.subject, "filename": s.attachment_filename,
        "email_time": s.email_timestamp.isoformat() if s.email_timestamp else None,
        "imported_at": s.import_timestamp.isoformat() if s.import_timestamp else None,
        "work_date": s.work_date.isoformat() if s.work_date else None,
        "status": s.import_status, "duplicate_status": s.duplicate_status, "duplicate_of": s.duplicate_of_id,
        "entries": s.entry_count, "hours": s.total_hours, "declared_total": s.declared_total_hours,
        "error": s.error_message, "has_file": bool(s.stored_path),
    }


@router.post("/sync", dependencies=[Depends(require_manager)])
def sync_now():
    return job_gmail_sync("manual")


@router.get("/gmail-status", dependencies=[Depends(require_viewer)])
def gmail_status(db: Session = Depends(get_db)):
    info = gmail_client.status()
    last = db.scalar(select(JobRun).where(JobRun.job == "gmail_sync").order_by(JobRun.id.desc()).limit(1))
    last_ok = db.scalar(select(JobRun).where(JobRun.job == "gmail_sync", JobRun.status == "ok").order_by(JobRun.id.desc()).limit(1))
    info.update({
        "last_run": {"at": last.started_at.isoformat(), "status": last.status, "message": last.message} if last else None,
        "last_success": last_ok.started_at.isoformat() if last_ok else None,
        "next_run": next_runs().get("gmail_sync"),
        "messages_seen": db.scalar(select(func.count(GmailMessage.id))),
    })
    # never expose file-system paths of secrets to the browser beyond their names
    info["credentials_file"] = Path(info["credentials_file"]).name
    info["token_file"] = Path(info["token_file"]).name
    return info


@router.post("/upload", dependencies=[Depends(require_manager)])
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 15 MB.")
    name = Path(file.filename or "upload.xlsx").name
    stored = store_file(content, name, prefix=f"upload_{sha256(content)[:10]}")
    subs = import_file(db, content, ImportContext(filename=name, source="upload"), stored)
    db.commit()
    names = {e.id: e.name for e in db.scalars(select(Employee))}
    return [submission_out(s, names.get(s.employee_id)) | {"issues": _issues(s)} for s in subs]


def _issues(s: Submission) -> list[dict]:
    return [{"severity": i.severity, "code": i.code, "message": i.message, "excel_row": i.excel_row} for i in s.issues]


@router.get("/submissions", dependencies=[Depends(require_viewer)])
def submissions(status: str | None = None, employee_id: int | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = (select(Submission, Employee.name).outerjoin(Employee, Employee.id == Submission.employee_id)
         .order_by(Submission.id.desc()).limit(min(limit, 500)))
    if status:
        q = q.where(Submission.import_status == status)
    if employee_id:
        q = q.where(Submission.employee_id == employee_id)
    rows = db.execute(q).all()
    counts = {}
    if rows:
        ids = [s.id for s, _ in rows]
        for sid, sev, n in db.execute(select(DataQualityIssue.submission_id, DataQualityIssue.severity, func.count())
                                      .where(DataQualityIssue.submission_id.in_(ids))
                                      .group_by(DataQualityIssue.submission_id, DataQualityIssue.severity)):
            counts.setdefault(sid, {})[sev] = n
    return [submission_out(s, name) | {"issue_counts": counts.get(s.id, {})} for s, name in rows]


@router.get("/submissions/{submission_id}", dependencies=[Depends(require_viewer)])
def submission_detail(submission_id: int, db: Session = Depends(get_db)):
    s = db.get(Submission, submission_id)
    if s is None:
        raise HTTPException(404, "Submission not found")
    out = submission_out(s, s.employee.name if s.employee else None)
    out["issues"] = _issues(s)
    out["entry_ids"] = [e.id for e in s.entries]
    return out


@router.get("/submissions/{submission_id}/file", dependencies=[Depends(require_viewer)])
def submission_file(submission_id: int, db: Session = Depends(get_db)):
    s = db.get(Submission, submission_id)
    if s is None or not s.stored_path:
        raise HTTPException(404, "File not available")
    path = Path(s.stored_path).resolve()
    if not path.is_relative_to(settings.imports_dir.resolve()) or not path.exists():
        raise HTTPException(404, "File not available")
    return FileResponse(path, filename=Path(s.attachment_filename.split(" [")[0]).name)


@router.delete("/submissions/{submission_id}", dependencies=[Depends(require_admin)])
def delete_submission(submission_id: int, db: Session = Depends(get_db)):
    """Remove a wrongly imported timesheet and its rows (the original file is kept on disk)."""
    s = db.get(Submission, submission_id)
    if s is None:
        raise HTTPException(404, "Submission not found")
    # clear references from later duplicates/resubmissions
    for other in db.scalars(select(Submission).where(Submission.duplicate_of_id == s.id)):
        other.duplicate_of_id = None
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/jobs", dependencies=[Depends(require_viewer)])
def jobs(job: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = select(JobRun).order_by(JobRun.id.desc()).limit(min(limit, 200))
    if job:
        q = q.where(JobRun.job == job)
    return [{"id": j.id, "job": j.job, "trigger": j.trigger, "started_at": j.started_at.isoformat(),
             "finished_at": j.finished_at.isoformat() if j.finished_at else None, "status": j.status, "message": j.message}
            for j in db.scalars(q)]
