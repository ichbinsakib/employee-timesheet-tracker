from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException


def parse_day(value: str | None, default: date | None = None) -> date:
    if not value:
        return default or date.today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"Invalid date '{value}'. Use YYYY-MM-DD.")


def parse_range(start: str | None, end: str | None, days: int = 30) -> tuple[date, date]:
    end_d = parse_day(end)
    start_d = parse_day(start, end_d - timedelta(days=max(days, 1) - 1))
    if start_d > end_d:
        raise HTTPException(400, "Start date is after end date.")
    if (end_d - start_d).days > 731:
        raise HTTPException(400, "Please choose a range of two years or less.")
    return start_d, end_d
