from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.analytics import kpi
from backend.api.common import parse_range
from backend.api.employees import entry_out
from backend.auth.deps import require_viewer
from backend.database.session import get_db
from backend.models import EntryActivity, Employee, TimesheetEntry, WorkCategory

router = APIRouter(prefix="/api", tags=["timesheets"], dependencies=[Depends(require_viewer)])


@router.get("/timesheets")
def list_entries(start: str | None = None, end: str | None = None, days: int = 30, employee_id: int | None = None,
                 category_id: int | None = None, completed: str | None = None, q: str | None = None,
                 page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    s, t = parse_range(start, end, days)
    page_size = min(max(page_size, 10), 200)
    query = (select(TimesheetEntry, Employee.name, WorkCategory.name)
             .join(Employee, Employee.id == TimesheetEntry.employee_id)
             .outerjoin(WorkCategory, WorkCategory.id == TimesheetEntry.primary_category_id)
             .where(TimesheetEntry.work_date >= s, TimesheetEntry.work_date <= t))
    if employee_id:
        query = query.where(TimesheetEntry.employee_id == employee_id)
    if category_id:
        # entries with at least one activity in this category
        query = query.where(TimesheetEntry.id.in_(select(EntryActivity.entry_id).where(EntryActivity.category_id == category_id)))
    if completed in ("yes", "no", "unknown"):
        query = query.where(TimesheetEntry.completed.is_(None) if completed == "unknown" else TimesheetEntry.completed.is_(completed == "yes"))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(TimesheetEntry.notes.ilike(like), TimesheetEntry.costing_code.ilike(like), Employee.name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    hours = db.scalar(select(func.sum(query.subquery().c.burden_hours)))
    rows = db.execute(query.order_by(TimesheetEntry.work_date.desc(), Employee.name, TimesheetEntry.original_excel_row)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for x, name, cat in rows:
        item = entry_out(x, cat)
        item["employee"] = name
        items.append(item)
    return {"total": total, "total_hours": round(hours or 0, 2), "page": page, "page_size": page_size,
            "period": {"start": s.isoformat(), "end": t.isoformat()}, "items": items}


@router.get("/timesheets/{entry_id}")
def entry_detail(entry_id: int, db: Session = Depends(get_db)):
    x = db.get(TimesheetEntry, entry_id)
    if x is None:
        raise HTTPException(404, "Entry not found")
    cats = kpi.categories(db)
    out = entry_out(x, cats[x.primary_category_id].name if x.primary_category_id in cats else None)
    out["employee"] = x.employee.name
    out["file"] = x.submission.attachment_filename
    out["activities"] = [
        {"text": a.text, "category": cats[a.category_id].name if a.category_id in cats else None,
         "keyword": a.matched_keyword, "hours": round(a.allocated_hours, 2)}
        for a in sorted(x.activities, key=lambda a: a.position)
    ]
    return out


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "description": c.description, "color": c.color}
            for c in db.scalars(select(WorkCategory).order_by(WorkCategory.name))]
