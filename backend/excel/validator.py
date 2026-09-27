"""Row-level value conversion and validation for parsed timesheets."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from backend.excel.parser import ParsedRow, ParsedSheet, parse_number

YES = {"yes", "y", "true", "done", "complete", "completed", "1", "✓", "✔"}
NO = {"no", "n", "false", "not complete", "incomplete", "in progress", "ongoing", "pending", "wip", "0"}

MAX_ROW_HOURS = 24.0
HIGH_DAY_HOURS = 16.0
SHORT_NOTE_CHARS = 12


@dataclass
class Issue:
    severity: str  # info | warning | error
    code: str
    message: str
    excel_row: int | None = None


@dataclass
class CleanRow:
    excel_row: int
    costing_code: str | None
    notes: str | None
    file_type: str | None
    completed: bool | None
    completed_raw: str | None
    feature_count: int | None
    burden_hours: float | None


@dataclass
class ValidatedSheet:
    rows: list[CleanRow] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    total_hours: float = 0.0


def parse_completed(raw: str | None) -> tuple[bool | None, bool]:
    """Return (value, recognised). None means not recorded."""
    if raw is None:
        return None, True
    text = raw.strip().lower().rstrip(".")
    if text in YES:
        return True, True
    if text in NO:
        return False, True
    return None, False


def validate_sheet(sheet: ParsedSheet, work_date: date | None, today: date | None = None) -> ValidatedSheet:
    today = today or date.today()
    out = ValidatedSheet()

    if work_date:
        if work_date > today + timedelta(days=1):
            out.issues.append(Issue("warning", "future_date", f"Timesheet date {work_date.isoformat()} is in the future."))
        elif work_date < today - timedelta(days=60):
            out.issues.append(Issue("info", "old_date", f"Timesheet date {work_date.isoformat()} is more than 60 days old."))

    for row in sheet.rows:
        out.rows.append(_validate_row(row, out.issues))

    out.total_hours = round(sum(r.burden_hours or 0 for r in out.rows), 2)

    if not out.rows:
        out.issues.append(Issue("error", "no_entries", "The timesheet table has no filled-in rows."))
    if out.total_hours > HIGH_DAY_HOURS:
        out.issues.append(Issue("warning", "high_total", f"Total recorded hours ({out.total_hours:g}) exceed {HIGH_DAY_HOURS:g}."))
    if out.rows and out.total_hours == 0:
        out.issues.append(Issue("warning", "zero_total", "Rows were filled in but no hours were recorded."))
    if sheet.declared_total is not None and abs(sheet.declared_total - out.total_hours) > 0.05:
        out.issues.append(Issue(
            "warning", "total_mismatch",
            f"The sheet's stated total ({sheet.declared_total:g} h) does not match the sum of the rows ({out.total_hours:g} h).",
            sheet.declared_total_row,
        ))
    return out


def _validate_row(row: ParsedRow, issues: list[Issue]) -> CleanRow:
    hours = parse_number(row.hours_raw)
    if row.hours_raw not in (None, "") and hours is None and str(row.hours_raw).strip() not in {"/", "-"}:
        issues.append(Issue("warning", "bad_hours", f"Hours value '{row.hours_raw}' is not a number.", row.excel_row))
    if hours is None:
        issues.append(Issue("warning", "missing_hours", "Row has no hours recorded.", row.excel_row))
    elif hours < 0 or hours > MAX_ROW_HOURS:
        issues.append(Issue("error", "invalid_hours", f"Row hours ({hours:g}) are outside 0–24; value ignored.", row.excel_row))
        hours = None

    completed, recognised = parse_completed(row.completed_raw)
    if not recognised:
        issues.append(Issue("warning", "bad_completed", f"Completed value '{row.completed_raw}' is not Yes/No.", row.excel_row))

    features: int | None = None
    feat = parse_number(row.feature_raw)
    if feat is not None:
        if feat < 0 or feat != int(feat):
            issues.append(Issue("warning", "bad_features", f"Feature count '{row.feature_raw}' is not a whole number.", row.excel_row))
        else:
            features = int(feat)
    elif row.feature_raw not in (None, "") and str(row.feature_raw).strip() not in {"/", "-"}:
        issues.append(Issue("warning", "bad_features", f"Feature count '{row.feature_raw}' is not a number.", row.excel_row))

    if not row.notes:
        issues.append(Issue("warning", "missing_notes", "Row has no notes describing the work.", row.excel_row))
    elif len(row.notes) < SHORT_NOTE_CHARS:
        issues.append(Issue("info", "short_notes", f"Notes are very short ('{row.notes}').", row.excel_row))
    if not row.costing_code:
        issues.append(Issue("info", "missing_costing_code", "Row has no costing code.", row.excel_row))

    return CleanRow(
        excel_row=row.excel_row,
        costing_code=row.costing_code,
        notes=row.notes,
        file_type=row.file_type,
        completed=completed,
        completed_raw=row.completed_raw,
        feature_count=features,
        burden_hours=hours,
    )
