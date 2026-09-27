from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.common import parse_day
from backend.auth.deps import require_manager, require_viewer
from backend.config import settings
from backend.database.session import get_db
from backend.models import GeneratedReport
from backend.reports.daily import EXPORTERS, MEDIA_TYPES, build_daily_report
from backend.services.scheduler import job_daily_report

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/daily", dependencies=[Depends(require_viewer)])
def daily(date: str | None = None, db: Session = Depends(get_db)):
    return build_daily_report(db, parse_day(date))


@router.get("/daily/export", dependencies=[Depends(require_viewer)])
def export(date: str | None = None, fmt: str = "xlsx", db: Session = Depends(get_db)):
    if fmt not in EXPORTERS:
        raise HTTPException(400, "Format must be xlsx, csv or pdf.")
    day = parse_day(date)
    content = EXPORTERS[fmt](build_daily_report(db, day))
    return Response(content, media_type=MEDIA_TYPES[fmt],
                    headers={"Content-Disposition": f'attachment; filename="daily_report_{day.isoformat()}.{fmt}"'})


@router.post("/generate", dependencies=[Depends(require_manager)])
def generate(date: str | None = None):
    paths = job_daily_report("manual", parse_day(date))
    return {"files": [Path(p).name for p in paths]}


@router.get("", dependencies=[Depends(require_viewer)])
def list_reports(db: Session = Depends(get_db)):
    rows = db.scalars(select(GeneratedReport).order_by(GeneratedReport.report_date.desc(), GeneratedReport.fmt).limit(300))
    return [{"id": r.id, "date": r.report_date.isoformat(), "fmt": r.fmt, "created_at": r.created_at.isoformat(),
             "exists": Path(r.path).exists()} for r in rows]


@router.get("/file/{report_id}", dependencies=[Depends(require_viewer)])
def download(report_id: int, db: Session = Depends(get_db)):
    r = db.get(GeneratedReport, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    path = Path(r.path).resolve()
    if not path.is_relative_to(settings.reports_dir.resolve()) or not path.exists():
        raise HTTPException(404, "Report file is missing")
    return FileResponse(path, media_type=MEDIA_TYPES[r.fmt], filename=path.name)
