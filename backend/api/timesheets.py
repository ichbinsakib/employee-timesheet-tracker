from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.api.common import parse_range
from backend.api.employees import entry_out
from backend.auth.deps import require_manager, require_viewer
from backend.database.session import get_db
from backend.models import CostingCode, Employee, TimesheetEntry, now
from backend.services import costing_codes as cc

router = APIRouter(prefix="/api", tags=["timesheets"])


@router.get("/timesheets", dependencies=[Depends(require_viewer)])
def list_entries(start: str | None = None, end: str | None = None, days: int = 30, employee_id: int | None = None,
                 costing_code: str | None = None, completed: str | None = None, q: str | None = None,
                 page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    s, t = parse_range(start, end, days)
    page_size = min(max(page_size, 10), 200)
    query = (select(TimesheetEntry, Employee.name)
             .join(Employee, Employee.id == TimesheetEntry.employee_id)
             .where(TimesheetEntry.work_date >= s, TimesheetEntry.work_date <= t))
    if employee_id:
        query = query.where(TimesheetEntry.employee_id == employee_id)
    if costing_code:
        if costing_code == cc.NO_CODE:
            query = query.where(or_(TimesheetEntry.costing_code.is_(None), TimesheetEntry.costing_code == ""))
        else:
            query = query.where(func.upper(TimesheetEntry.costing_code) == costing_code.strip().upper())
    if completed in ("yes", "no", "unknown"):
        query = query.where(TimesheetEntry.completed.is_(None) if completed == "unknown" else TimesheetEntry.completed.is_(completed == "yes"))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(TimesheetEntry.notes.ilike(like), TimesheetEntry.costing_code.ilike(like), Employee.name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    hours = db.scalar(select(func.sum(query.subquery().c.burden_hours)))
    rows = db.execute(query.order_by(TimesheetEntry.work_date.desc(), Employee.name, TimesheetEntry.original_excel_row)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    desc = cc.descriptions(db)
    items = []
    for x, name in rows:
        item = entry_out(x, desc)
        item["employee"] = name
        items.append(item)
    return {"total": total, "total_hours": round(hours or 0, 2), "page": page, "page_size": page_size,
            "period": {"start": s.isoformat(), "end": t.isoformat()}, "items": items}


@router.get("/timesheets/{entry_id}", dependencies=[Depends(require_viewer)])
def entry_detail(entry_id: int, db: Session = Depends(get_db)):
    x = db.get(TimesheetEntry, entry_id)
    if x is None:
        raise HTTPException(404, "Entry not found")
    out = entry_out(x, cc.descriptions(db))
    out["employee"] = x.employee.name
    out["file"] = x.submission.attachment_filename
    return out


# --------------------------------------------------------------------------- costing codes
class CodeIn(BaseModel):
    description: str = Field("", max_length=500)


@router.get("/costing-codes", dependencies=[Depends(require_viewer)])
def list_codes(db: Session = Depends(get_db)):
    """Every code in the list (from the timesheets' COSTING CODE sheet) plus codes used but not listed."""
    return cc.all_codes_with_usage(db)


@router.put("/costing-codes/{code}", dependencies=[Depends(require_manager)])
def update_code(code: str, body: CodeIn, db: Session = Depends(get_db)):
    """Set a description by hand; timesheet updates will not overwrite it afterwards."""
    code = code.strip().upper()
    row = db.get(CostingCode, code)
    if row is None:
        row = CostingCode(code=code)
        db.add(row)
    row.description = cc.clean_description(body.description)
    row.source, row.updated_at = "manual", now()
    db.commit()
    return {"code": row.code, "description": row.description, "source": row.source}
