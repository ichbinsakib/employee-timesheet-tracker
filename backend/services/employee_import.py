"""Import employees from a CSV or Excel file (e.g. an export from the HR system).

Columns are found by header name, in any order; only a name column is required:

    name | full_name | employee | employee name      -> name
    email | e-mail | email address                   -> email
    department | dept                                -> department
    designation | job title | job_title | title | position -> job title
    status | active                                  -> active / inactive
    aliases | other spellings                        -> extra spellings used on timesheets
    working days | expected daily hours | expected weekly hours | deadline  (optional)

Rows are matched to existing employees by email, then by name (ignoring honorifics
such as "Md."). When the file's name differs from the stored one, the stored spelling
is kept as an alias so timesheets signed that way still match. Settings that are not
in the file (working days, hours, deadline) are left unchanged. People marked as
terminated/inactive are never created, only deactivated if they already exist.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from backend.models import Employee
from backend.services import employees as emp_svc

HEADERS: dict[str, list[str]] = {
    "name": ["name", "full name", "full_name", "employee", "employee name", "employee_name"],
    "email": ["email", "e-mail", "email address", "mail"],
    "department": ["department", "dept"],
    "job_title": ["designation", "job title", "job_title", "title", "position", "role"],
    "status": ["status", "active", "employment status"],
    "aliases": ["aliases", "other spellings", "alias"],
    "working_days": ["working days", "working_days", "workdays"],
    "expected_daily_hours": ["expected daily hours", "expected_daily_hours", "daily hours", "hours per day"],
    "expected_weekly_hours": ["expected weekly hours", "expected_weekly_hours", "weekly hours", "hours per week"],
    "submission_deadline": ["deadline", "submission deadline", "submission_deadline"],
}
INACTIVE = {"terminated", "inactive", "left", "resigned", "no", "false", "0", "former"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEADLINE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MAX_ROWS = 2000


class EmployeeImportError(ValueError):
    pass


@dataclass
class ImportResult:
    rows: int = 0
    created: list[str] = field(default_factory=list)
    updated: list[dict] = field(default_factory=list)  # {"name", "changes": [...]}
    deactivated: list[str] = field(default_factory=list)
    reactivated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"row", "reason"}
    columns: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("rows", "created", "updated", "deactivated", "reactivated", "unchanged", "skipped", "columns")}


def _norm(h: object) -> str:
    return re.sub(r"\s+", " ", str(h or "").replace("﻿", "").strip().lower())


def read_table(content: bytes, filename: str) -> list[list[object]]:
    ext = Path(filename).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        except Exception as exc:  # noqa: BLE001
            raise EmployeeImportError(f"Could not open the Excel file ({exc}).")
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if ext in (".csv", ".txt"):
        text = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [row for row in csv.reader(io.StringIO(text), dialect)]
    raise EmployeeImportError("Upload a .csv or .xlsx file.")


def find_columns(table: list[list[object]]) -> tuple[int, dict[str, int]]:
    """Header row = first of the first 10 rows that contains a name column."""
    for r_idx, row in enumerate(table[:10]):
        cols: dict[str, int] = {}
        for c_idx, cell in enumerate(row):
            h = _norm(cell)
            for key, names in HEADERS.items():
                if h in names and key not in cols:
                    cols[key] = c_idx
        if "name" in cols:
            return r_idx, cols
    raise EmployeeImportError("No name column found. The first row should have headers such as 'full_name' or 'Name'.")


def _cell(row: list[object], idx: int | None) -> str | None:
    if idx is None or idx >= len(row) or row[idx] is None:
        return None
    if isinstance(row[idx], float) and float(row[idx]).is_integer():
        return str(int(row[idx]))
    s = str(row[idx]).strip()
    return s or None


def import_employees(db: Session, content: bytes, filename: str) -> ImportResult:
    """Apply the file to the database session. The caller commits (apply) or rolls back (preview)."""
    table = read_table(content, filename)
    header_idx, cols = find_columns(table)
    data = [r for r in table[header_idx + 1:] if any(c not in (None, "") for c in r)]
    if len(data) > MAX_ROWS:
        raise EmployeeImportError(f"The file has more than {MAX_ROWS} rows.")
    result = ImportResult(rows=len(data), columns=sorted(cols))
    seen: set[int] = set()

    for offset, row in enumerate(data):
        excel_row = header_idx + offset + 2
        name = _cell(row, cols.get("name"))
        if not name:
            result.skipped.append({"row": excel_row, "reason": "No name"})
            continue
        email = (_cell(row, cols.get("email")) or "").lower() or None
        if email and not EMAIL_RE.match(email):
            result.skipped.append({"row": excel_row, "reason": f"'{email}' is not a valid email; row skipped"})
            continue
        status = _cell(row, cols.get("status"))
        active = not (status and status.strip().lower() in INACTIVE)

        values: dict[str, object] = {}
        for key in ("department", "job_title", "aliases", "working_days", "submission_deadline"):
            v = _cell(row, cols.get(key))
            if v:
                values[key] = v
        for key in ("expected_daily_hours", "expected_weekly_hours"):
            v = _cell(row, cols.get(key))
            if v:
                try:
                    values[key] = float(v)
                except ValueError:
                    result.skipped.append({"row": excel_row, "reason": f"{key.replace('_', ' ')} '{v}' is not a number; value ignored"})
        if "submission_deadline" in values and not DEADLINE_RE.match(str(values["submission_deadline"])):
            result.skipped.append({"row": excel_row, "reason": f"deadline '{values.pop('submission_deadline')}' is not HH:MM; value ignored"})

        emp = emp_svc.find_by_email(db, email) if email else None
        if emp is None:
            emp = emp_svc.find_by_name(db, name)
        if emp is not None and emp.id in seen:
            result.skipped.append({"row": excel_row, "reason": f"Duplicate of an earlier row for {emp.name}"})
            continue

        if emp is None:
            if not active:
                result.skipped.append({"row": excel_row, "reason": f"{name} is marked '{status}' and not in the app; not added"})
                continue
            emp = Employee(name=name, email=email, active=True, tracking_start=date.today(), **values)
            db.add(emp)
            db.flush()
            seen.add(emp.id)
            result.created.append(name)
            continue

        seen.add(emp.id)
        changes: list[str] = []
        if emp.name != name:
            aliases = [a.strip() for a in (emp.aliases or "").split(",") if a.strip()]
            if emp.name not in aliases:
                aliases.append(emp.name)
            changes.append(f"name '{emp.name}' → '{name}' (old spelling kept as alias)")
            emp.name, emp.aliases = name, ", ".join(aliases)
        if email and emp.email != email:
            changes.append(f"email → {email}")
            emp.email = email
        for key, v in values.items():
            if key == "aliases":
                current = [a.strip() for a in (emp.aliases or "").split(",") if a.strip()]
                new = [a.strip() for a in str(v).split(",") if a.strip() and a.strip() not in current]
                if new:
                    emp.aliases = ", ".join(current + new)
                    changes.append(f"aliases + {', '.join(new)}")
            elif getattr(emp, key) != v:
                changes.append(f"{key.replace('_', ' ')} → {v}")
                setattr(emp, key, v)
        if emp.auto_created:
            emp.auto_created = False
            changes.append("reviewed (was added automatically)")
        if emp.active != active:
            (result.reactivated if active else result.deactivated).append(emp.name)
            emp.active = active
        if changes:
            result.updated.append({"name": emp.name, "changes": changes})
        elif emp.name not in result.deactivated + result.reactivated:
            result.unchanged.append(emp.name)
    db.flush()
    return result
