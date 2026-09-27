from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth import security
from backend.auth.deps import current_user, require_admin, require_manager, require_viewer
from backend.config import settings
from backend.database.session import get_db
from backend.models import AccessLog, ClassificationRule, EntryActivity, TimesheetEntry, User, WorkCategory
from backend.services import app_settings
from backend.services import backup as backup_svc
from backend.services import scheduler
from backend.services.importer import reclassify_all

router = APIRouter(prefix="/api/settings", tags=["settings"])

EDITABLE = {
    "gmail_query": str, "gmail_lookback_days": int, "gmail_allowed_senders": str, "sync_interval_minutes": int,
    "backup_interval_hours": int, "backup_retention": int, "daily_report_time": str, "holidays": str,
    "unusual_hours_threshold": float,
}


# --------------------------------------------------------------------------- general
@router.get("", dependencies=[Depends(require_viewer)])
def get_settings(db: Session = Depends(get_db)):
    return {
        "values": app_settings.all_settings(db),
        "system": {
            "data_dir": str(settings.data_dir), "database": str(settings.database_path) if settings.is_sqlite else "(external database)",
            "backup_dir": str(settings.backup_dir), "reports_dir": str(settings.reports_dir),
            "imports_dir": str(settings.imports_dir), "logs_dir": str(settings.logs_dir),
            "host": settings.host, "port": settings.port,
            "database_size": settings.database_path.stat().st_size if settings.is_sqlite and settings.database_path.exists() else None,
            "disk_free": backup_svc.disk_free(settings.data_dir),
            "scheduler": scheduler.next_runs(),
        },
    }


@router.put("", dependencies=[Depends(require_admin)])
def update_settings(values: dict[str, str], db: Session = Depends(get_db)):
    for key, raw in values.items():
        if key not in EDITABLE:
            raise HTTPException(400, f"Unknown setting '{key}'")
        raw = str(raw).strip()
        if EDITABLE[key] in (int, float):
            try:
                num = EDITABLE[key](raw)
            except ValueError:
                raise HTTPException(400, f"'{key}' must be a number")
            if num < (0 if key != "sync_interval_minutes" else 1) or num > 100000:
                raise HTTPException(400, f"'{key}' is out of range")
        if key == "daily_report_time" and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", raw):
            raise HTTPException(400, "Report time must be HH:MM (24-hour)")
        if key == "holidays":
            for part in filter(None, (p.strip() for p in raw.replace(";", ",").split(","))):
                try:
                    date.fromisoformat(part)
                except ValueError:
                    raise HTTPException(400, f"Holiday '{part}' is not a YYYY-MM-DD date")
        app_settings.set_value(db, key, raw)
    db.commit()
    scheduler.reschedule()
    return app_settings.all_settings(db)


# --------------------------------------------------------------------------- categories & rules
class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    color: str | None = None


class RuleIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    category_id: int
    priority: int = Field(50, ge=0, le=1000)
    active: bool = True


@router.get("/rules", dependencies=[Depends(require_viewer)])
def list_rules(db: Session = Depends(get_db)):
    return [{"id": r.id, "keyword": r.keyword, "category_id": r.category_id, "category": r.category.name,
             "priority": r.priority, "active": r.active}
            for r in db.scalars(select(ClassificationRule).order_by(ClassificationRule.priority.desc(), ClassificationRule.keyword))]


@router.post("/rules", dependencies=[Depends(require_admin)])
def add_rule(body: RuleIn, db: Session = Depends(get_db)):
    if db.get(WorkCategory, body.category_id) is None:
        raise HTTPException(400, "Unknown category")
    r = ClassificationRule(**body.model_dump())
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.put("/rules/{rule_id}", dependencies=[Depends(require_admin)])
def update_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db)):
    r = db.get(ClassificationRule, rule_id)
    if r is None:
        raise HTTPException(404, "Rule not found")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/rules/{rule_id}", dependencies=[Depends(require_admin)])
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(ClassificationRule, rule_id)
    if r:
        db.delete(r)
        db.commit()
    return {"ok": True}


@router.post("/categories", dependencies=[Depends(require_admin)])
def add_category(body: CategoryIn, db: Session = Depends(get_db)):
    if db.scalar(select(WorkCategory).where(WorkCategory.name == body.name.strip())):
        raise HTTPException(409, "A category with that name exists")
    c = WorkCategory(name=body.name.strip(), description=body.description, color=body.color or "#64748b")
    db.add(c)
    db.commit()
    return {"id": c.id}


@router.put("/categories/{category_id}", dependencies=[Depends(require_admin)])
def update_category(category_id: int, body: CategoryIn, db: Session = Depends(get_db)):
    c = db.get(WorkCategory, category_id)
    if c is None:
        raise HTTPException(404, "Category not found")
    c.name, c.description = body.name.strip(), body.description
    if body.color:
        c.color = body.color
    db.commit()
    return {"ok": True}


@router.delete("/categories/{category_id}", dependencies=[Depends(require_admin)])
def delete_category(category_id: int, db: Session = Depends(get_db)):
    c = db.get(WorkCategory, category_id)
    if c is None:
        raise HTTPException(404, "Category not found")
    if c.name == "Uncategorized":
        raise HTTPException(400, "The Uncategorized category is required")
    used = db.scalar(select(ClassificationRule.id).where(ClassificationRule.category_id == c.id).limit(1)) \
        or db.scalar(select(EntryActivity.id).where(EntryActivity.category_id == c.id).limit(1)) \
        or db.scalar(select(TimesheetEntry.id).where(TimesheetEntry.primary_category_id == c.id).limit(1))
    if used:
        raise HTTPException(400, "Category is in use. Move its rules and re-run classification first.")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/reclassify", dependencies=[Depends(require_admin)])
def reclassify(db: Session = Depends(get_db)):
    n = reclassify_all(db)
    db.commit()
    return {"activities": n}


# --------------------------------------------------------------------------- backups
class RestoreIn(BaseModel):
    name: str
    confirm: str


@router.get("/backups", dependencies=[Depends(require_manager)])
def backups():
    return {"dir": str(settings.backup_dir), "backups": backup_svc.list_backups()}


@router.post("/backups", dependencies=[Depends(require_manager)])
def backup_now():
    try:
        name = scheduler.job_backup("manual")
    except backup_svc.BackupError as exc:
        raise HTTPException(400, str(exc))
    return {"name": name}


@router.post("/backups/validate", dependencies=[Depends(require_admin)])
def validate(body: RestoreIn):
    try:
        return {"counts": backup_svc.validate_backup(backup_svc.resolve_backup(body.name))}
    except backup_svc.BackupError as exc:
        raise HTTPException(400, str(exc))


@router.post("/backups/restore")
def restore(body: RestoreIn, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.confirm != "RESTORE":
        raise HTTPException(400, "Type RESTORE to confirm. This replaces the current database.")
    try:
        path = backup_svc.resolve_backup(body.name)
        db.close()
        result = backup_svc.restore_backup(path)
    except backup_svc.BackupError as exc:
        raise HTTPException(400, str(exc))
    from backend.database.session import session_scope
    with session_scope() as s:
        s.add(AccessLog(username=user.username, ip=security.client_ip(request), via=security.access_channel(request),
                        event="db_restore", method="POST", path=f"restore:{body.name}"))
    return result


@router.post("/backups/upload", dependencies=[Depends(require_admin)])
async def upload_backup(file: UploadFile = File(...)):
    content = await file.read(512 * 1024 * 1024)
    try:
        path = backup_svc.save_uploaded_backup(content, file.filename or "upload.db")
    except backup_svc.BackupError as exc:
        raise HTTPException(400, str(exc))
    return {"name": path.name}


# --------------------------------------------------------------------------- users
class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str | None = None
    role: str = "manager"
    active: bool = True


@router.get("/users", dependencies=[Depends(require_admin)])
def users(db: Session = Depends(get_db)):
    return [{"id": u.id, "username": u.username, "role": u.role, "active": u.active,
             "last_login": u.last_login.isoformat() if u.last_login else None} for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", dependencies=[Depends(require_admin)])
def create_user(body: UserIn, db: Session = Depends(get_db)):
    if body.role not in security.ROLES:
        raise HTTPException(400, "Role must be admin, manager or viewer")
    if db.scalar(select(User).where(User.username == body.username.strip())):
        raise HTTPException(409, "Username already exists")
    if err := security.validate_new_password(body.password or ""):
        raise HTTPException(400, err)
    u = User(username=body.username.strip(), password_hash=security.hash_password(body.password), role=body.role, active=body.active)
    db.add(u)
    db.commit()
    return {"id": u.id}


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if body.role not in security.ROLES:
        raise HTTPException(400, "Role must be admin, manager or viewer")
    if u.id == me.id and (body.role != "admin" or not body.active):
        raise HTTPException(400, "You cannot remove your own administrator access.")
    u.username, u.role, u.active = body.username.strip(), body.role, body.active
    if body.password:
        if err := security.validate_new_password(body.password):
            raise HTTPException(400, err)
        u.password_hash = security.hash_password(body.password)
        security.end_all_sessions(db, u.id)
    if not u.active:
        security.end_all_sessions(db, u.id)
    db.commit()
    return {"ok": True}


@router.get("/access-log", dependencies=[Depends(require_admin)])
def access_log(limit: int = 200, remote_only: bool = False, db: Session = Depends(get_db)):
    q = select(AccessLog).order_by(AccessLog.id.desc()).limit(min(limit, 1000))
    if remote_only:
        q = q.where(AccessLog.via != "local")
    return [{"ts": a.ts.isoformat(), "user": a.username, "ip": a.ip, "via": a.via, "event": a.event,
             "method": a.method, "path": a.path, "status": a.status} for a in db.scalars(q)]


@router.get("/whoami", dependencies=[Depends(current_user)])
def whoami(request: Request):
    return {"ip": security.client_ip(request), "via": security.access_channel(request), "https": security.is_https(request)}
