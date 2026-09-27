"""Employee identification from timesheet names and sender emails."""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import Employee

HONORIFICS = {"md", "mohammad", "mohammed", "muhammad", "mr", "mrs", "ms", "miss", "dr", "eng", "engr"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def name_tokens(name: str, drop_honorifics: bool = True) -> list[str]:
    tokens = re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split()
    if drop_honorifics:
        stripped = [t for t in tokens if t not in HONORIFICS]
        return stripped or tokens
    return tokens


def normalize_name(name: str) -> str:
    return " ".join(name_tokens(name, drop_honorifics=False))


def employee_names(emp: Employee) -> list[str]:
    names = [emp.name]
    names += [a.strip() for a in (emp.aliases or "").split(",") if a.strip()]
    return names


def find_by_name(db: Session, name: str) -> Employee | None:
    target = normalize_name(name)
    target_core = set(name_tokens(name))
    employees = list(db.scalars(select(Employee)))
    for emp in employees:
        if any(normalize_name(n) == target for n in employee_names(emp)):
            return emp
    # Same name ignoring honorifics ("Md. Kamrul Hasan" == "Kamrul Hasan")
    candidates = [e for e in employees if any(set(name_tokens(n)) == target_core for n in employee_names(e))]
    if len(candidates) == 1:
        return candidates[0]
    # One name contains the other (at least two words in common)
    if len(target_core) >= 2:
        candidates = [
            e for e in employees
            if any(len(target_core & set(name_tokens(n))) >= 2 and (target_core <= set(name_tokens(n)) or set(name_tokens(n)) <= target_core)
                   for n in employee_names(e))
        ]
        if len(candidates) == 1:
            return candidates[0]
    return None


def find_by_email(db: Session, email: str | None) -> Employee | None:
    if not email:
        return None
    return db.scalar(select(Employee).where(func.lower(Employee.email) == email.strip().lower()))


def working_days(emp: Employee) -> set[int]:
    """Weekday numbers (Mon=0) the employee is expected to work."""
    out = set()
    for part in (emp.working_days or "").split(","):
        part = part.strip()[:3].title()
        if part in WEEKDAYS:
            out.add(WEEKDAYS.index(part))
    return out or {0, 1, 2, 3, 4}


def expected_on(emp: Employee, day: date, holidays: set[date]) -> bool:
    if not emp.active or day in holidays or day.weekday() not in working_days(emp):
        return False
    start = emp.tracking_start or (emp.created_at.date() if emp.created_at else None)
    return start is None or day >= start
