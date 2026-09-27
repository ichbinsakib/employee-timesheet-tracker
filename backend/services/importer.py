"""Import pipeline: Excel bytes -> validated, classified rows in the database.

Used by both the Gmail sync and manual uploads, so they behave identically.

Duplicate handling
------------------
* Same Gmail message: skipped before we get here (see gmail/sync.py).
* Same file content (SHA-256) already imported: recorded as `duplicate`, no rows stored.
* Different file for an employee + date that already has a timesheet: treated as a
  corrected resubmission. The newer file replaces the older one (older is marked
  `superseded`, its rows are removed) and an info issue records it.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.excel.parser import ParsedSheet, date_from_filename, parse_workbook
from backend.excel.validator import Issue, validate_sheet
from backend.models import DataQualityIssue, EntryActivity, Employee, Submission, TimesheetEntry
from backend.services import employees as emp_svc
from backend.services.classifier import WEAK_PRIORITY, Classifier, normalize_activity, split_notes

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("imported", "imported_with_warnings")
EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}


@dataclass
class ImportContext:
    filename: str
    source: str = "upload"
    gmail_message_id: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    email_timestamp: datetime | None = None


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_file(content: bytes, filename: str, prefix: str) -> Path:
    """Keep a copy of every received file under imports/YYYY/MM/ as evidence."""
    now = datetime.now()
    folder = settings.imports_dir / f"{now:%Y}" / f"{now:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in Path(filename).name)[:150]
    path = folder / f"{prefix}_{safe}"
    path.write_bytes(content)
    return path


def import_file(db: Session, content: bytes, ctx: ImportContext, stored_path: Path | None = None) -> list[Submission]:
    """Import one Excel file. Returns the Submission rows created (one per timesheet sheet).

    The caller commits.
    """
    digest = sha256(content)
    stored = str(stored_path) if stored_path else None

    def base_submission(**kw) -> Submission:
        return Submission(
            source=ctx.source, gmail_message_id=ctx.gmail_message_id, sender_email=ctx.sender_email,
            subject=ctx.subject, attachment_filename=ctx.filename, file_sha256=digest, stored_path=stored,
            email_timestamp=ctx.email_timestamp, **kw,
        )

    if Path(ctx.filename).suffix.lower() not in EXCEL_EXTENSIONS:
        sub = base_submission(import_status="failed", error_message="Only .xlsx and .xlsm files are supported. Please save the timesheet as .xlsx.")
        db.add(sub)
        return [sub]

    earlier = db.scalar(
        select(Submission).where(Submission.file_sha256 == digest, Submission.import_status.in_(ACTIVE_STATUSES + ("superseded",)))
        .order_by(Submission.id)
    )
    if earlier is not None:
        sub = base_submission(
            import_status="duplicate", duplicate_status="duplicate_file", duplicate_of_id=earlier.id,
            employee_id=earlier.employee_id, work_date=earlier.work_date,
            error_message=f"Identical file already imported (submission #{earlier.id}); nothing new stored.",
        )
        db.add(sub)
        return [sub]

    parsed = parse_workbook(content)
    if parsed.error:
        sub = base_submission(import_status="failed", error_message=parsed.error)
        db.add(sub)
        return [sub]

    classifier = Classifier(db)
    multi = len(parsed.sheets) > 1
    created: list[Submission] = []
    for sheet in parsed.sheets:
        sub = base_submission()
        if multi:
            sub.attachment_filename = f"{ctx.filename} [{sheet.sheet_name}]"
        db.add(sub)
        _import_sheet(db, sub, sheet, ctx, classifier)
        created.append(sub)
    return created


def _import_sheet(db: Session, sub: Submission, sheet: ParsedSheet, ctx: ImportContext, classifier: Classifier) -> None:
    issues: list[Issue] = []

    # ---- employee
    employee = emp_svc.find_by_name(db, sheet.employee_name) if sheet.employee_name else None
    by_email = emp_svc.find_by_email(db, ctx.sender_email)
    if employee and by_email and employee.id != by_email.id:
        issues.append(Issue("info", "sender_differs", f"Sent from {ctx.sender_email} ({by_email.name}) but the sheet names {employee.name}; recorded under {employee.name}."))
    if employee is None and by_email is not None:
        employee = by_email
        if sheet.employee_name:
            issues.append(Issue("warning", "name_unmatched", f"Name on sheet '{sheet.employee_name}' did not match an employee; identified by sender email as {employee.name}."))
        else:
            issues.append(Issue("warning", "missing_name", f"No employee name on the sheet; identified by sender email as {employee.name}."))

    # ---- date
    work_date = sheet.work_date
    if work_date is None:
        if sheet.work_date_raw not in (None, ""):
            issues.append(Issue("warning", "bad_date", f"Could not read the date '{sheet.work_date_raw}'."))
        work_date = date_from_filename(ctx.filename)
        if work_date:
            issues.append(Issue("warning", "date_from_filename", f"Date taken from the file name ({work_date.isoformat()})."))
        elif ctx.email_timestamp:
            work_date = ctx.email_timestamp.date()
            issues.append(Issue("warning", "date_from_email", f"No date on the sheet; used the email date ({work_date.isoformat()})."))

    if work_date is None:
        _fail(db, sub, issues, "No date found on the sheet, in the file name or in the email.")
        return

    if employee is None:
        if not sheet.employee_name:
            _fail(db, sub, issues, "Could not identify the employee: no name on the sheet and the sender email is not linked to an employee.")
            return
        employee = Employee(
            name=sheet.employee_name, email=ctx.sender_email, auto_created=True, tracking_start=work_date,
        )
        db.add(employee)
        db.flush()
        issues.append(Issue("info", "employee_created", f"New employee '{employee.name}' was added automatically. Review their details in Employees."))
    elif ctx.sender_email and not employee.email:
        employee.email = ctx.sender_email

    sub.employee_id = employee.id
    sub.work_date = work_date

    validated = validate_sheet(sheet, work_date)
    issues.extend(validated.issues)
    if working := emp_svc.working_days(employee):
        if work_date.weekday() not in working:
            issues.append(Issue("info", "non_working_day", f"{work_date:%A} is not one of {employee.name}'s working days."))

    if not validated.rows:
        _fail(db, sub, issues, "The timesheet table has no filled-in rows.")
        return

    # ---- resubmission for same employee + date replaces the earlier one
    previous = list(db.scalars(
        select(Submission).where(
            Submission.employee_id == employee.id, Submission.work_date == work_date,
            Submission.import_status.in_(ACTIVE_STATUSES), Submission.id != sub.id,
        )
    ))
    for prev in previous:
        prev.import_status = "superseded"
        for entry in list(prev.entries):
            db.delete(entry)
        prev.entry_count = 0
        sub.duplicate_status = "resubmission"
        sub.duplicate_of_id = prev.id
        issues.append(Issue("info", "resubmission", f"Replaced an earlier timesheet for this date (submission #{prev.id}, '{prev.attachment_filename}')."))

    # ---- store rows
    for row in validated.rows:
        split = split_notes(row.notes)
        entry = TimesheetEntry(
            submission=sub, employee_id=employee.id, work_date=work_date,
            costing_code=row.costing_code, title=split.title, notes=row.notes, file_type=row.file_type,
            completed=row.completed, completed_raw=row.completed_raw, feature_count=row.feature_count,
            burden_hours=row.burden_hours, original_excel_row=row.excel_row, sheet_name=sheet.sheet_name,
        )
        db.add(entry)
        activities = split.activities or ([split.title] if split.title else [])
        share = (row.burden_hours or 0) / len(activities) if activities else 0
        for pos, text in enumerate(activities):
            entry.activities.append(EntryActivity(
                position=pos, text=text[:2000], normalized=normalize_activity(text), allocated_hours=round(share, 4),
            ))
        _classify_entry(entry, classifier)

    sub.entry_count = len(validated.rows)
    sub.total_hours = validated.total_hours
    sub.declared_total_hours = sheet.declared_total
    has_warnings = any(i.severity in ("warning", "error") for i in issues)
    sub.import_status = "imported_with_warnings" if has_warnings else "imported"
    _store_issues(db, sub, issues)


def _fail(db: Session, sub: Submission, issues: list[Issue], message: str) -> None:
    sub.import_status = "failed"
    sub.error_message = message
    issues.append(Issue("error", "import_failed", message))
    _store_issues(db, sub, issues)


def _store_issues(db: Session, sub: Submission, issues: list[Issue]) -> None:
    for i in issues:
        sub.issues.append(DataQualityIssue(
            employee_id=sub.employee_id, work_date=sub.work_date, severity=i.severity,
            code=i.code, message=i.message, excel_row=i.excel_row,
        ))


def _classify_entry(entry: TimesheetEntry, classifier: Classifier) -> None:
    """Classify each activity line. Lines matching no keyword, or only a generic one
    ("update", "sheet"), inherit the entry heading's category
    ("Bracket assembly drawing" / "-Add weld notes" -> Design & Engineering)."""
    title_cat, title_kw = classifier.classify(entry.title) if entry.title else (None, None)
    hours_by_cat: dict[int | None, float] = {}
    for act in entry.activities:
        cat_id, keyword, priority = classifier.classify_full(act.text)
        if title_kw and priority < WEAK_PRIORITY:
            cat_id, keyword = title_cat, f"{title_kw} (from heading)"
        act.category_id, act.matched_keyword = cat_id, keyword
        hours_by_cat[cat_id] = hours_by_cat.get(cat_id, 0) + (act.allocated_hours or 0)
    # Primary category: the title's category if it matches a rule, else the largest share
    if title_kw:
        entry.primary_category_id = title_cat
    elif hours_by_cat:
        entry.primary_category_id = max(hours_by_cat.items(), key=lambda kv: kv[1])[0]
    else:
        entry.primary_category_id = classifier.uncategorized_id


def reclassify_all(db: Session) -> int:
    """Re-run classification on every stored activity (after rules change)."""
    classifier = Classifier(db)
    count = 0
    for entry in db.scalars(select(TimesheetEntry)):
        _classify_entry(entry, classifier)
        count += len(entry.activities)
    return count
