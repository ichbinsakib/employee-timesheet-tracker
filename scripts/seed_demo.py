"""Fill a SEPARATE demo data folder with realistic sample timesheets, to try the app.

    python scripts/seed_demo.py --home C:\\Temp\\timesheet-demo
    set TIMESHEET_HOME=C:\\Temp\\timesheet-demo  &&  python run_server.py

Refuses to run against a folder that already has a database, so it can never
touch your real data.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NOTES = {
    "coordination": [
        "Co-ordination task\n-SO Release\n-Update SO tracker sheet\n- Kanban checking\n-Teams & Email comunication for followup\n-Approve the invoice.",
        "Co-ordination task\n-Future CO shortage data analysis.\n-Master Shudule sheet update for CO shortage\n- Making Subcontract PO\n-Communication with production",
        "Co-ordination task\n-Checking the RMA sheet\n-Through Purchasing 2, get vendor quotations and check them.\n-Entering data in the Matrix data entry sheet.\n-Make IT ticket for Days Behind App",
    ],
    "design": [
        ("Bracket assembly drawing rev B\n-Update dimensions\n-Add weld notes", "Assembly Drawing"),
        ("Frame model for new conveyor\n-Sheet metal features\n-Hole pattern", "Model"),
        ("Detail drawings for guard panels", "Drawing"),
        ("Top-level assembly for press line\n-Mate fixes\n-Interference check", "Assembly"),
        ("Engineering meeting with production team", None),
        ("BOM update for job P4410\n-Check purchased parts", None),
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True, help="Empty folder for the demo data")
    ap.add_argument("--weeks", type=int, default=8)
    args = ap.parse_args()
    home = Path(args.home).resolve()
    if (home / "data" / "timesheets.db").exists():
        sys.exit(f"{home} already has a database. Choose an empty folder for demo data.")
    os.environ["TIMESHEET_HOME"] = str(home)
    os.environ.pop("DATABASE_URL", None)

    from backend.database import init_db, session_scope
    from backend.models import Employee
    from backend.services.importer import ImportContext, import_file
    from scripts.make_sample_timesheet import REAL_EXAMPLE_NOTES, build_timesheet

    init_db()
    rng = random.Random(42)
    today = date.today()
    start = today - timedelta(weeks=args.weeks)
    people = [
        ("Md. Kamrul Hasan", "coordination", "Operations", "Coordinator"),
        ("Sarah Lee", "design", "Engineering", "Design Engineer"),
        ("Tanvir Ahmed", "design", "Engineering", "CAD Technician"),
        ("Priya Nair", "coordination", "Operations", "Planner"),
    ]
    with session_scope() as db:
        for name, _, dept, title in people:
            db.add(Employee(name=name, department=dept, job_title=title, tracking_start=start,
                            email=name.lower().replace(".", "").replace(" ", ".") + "@example.com"))

    tmp = Path(tempfile.mkdtemp())
    count = 0
    d = start
    while d < today:
        if d.weekday() < 5:
            for name, kind, _, _ in people:
                if rng.random() < 0.06:  # occasionally missing
                    continue
                if kind == "coordination":
                    notes = REAL_EXAMPLE_NOTES if name.startswith("Md.") and rng.random() < 0.3 else rng.choice(NOTES["coordination"])
                    hours = round(rng.choice([8, 8.5, 9, 9.5, 10.4]) + (4 if rng.random() < 0.03 else 0), 1)
                    rows = [("P4627", notes, "/", "/", "/", hours)]
                else:
                    rows = []
                    left = rng.choice([8, 8, 8.5, 9])
                    for i in range(rng.randint(2, 4)):
                        text, ftype = rng.choice(NOTES["design"])
                        h = left if i == 3 or rng.random() < 0.3 else round(min(left, rng.choice([1, 1.5, 2, 2.5, 3])), 1)
                        left = round(left - h, 1)
                        rows.append((f"P{rng.randint(4400, 4700)}", text, ftype or "/", rng.choice(["Yes", "Yes", "No"]),
                                     rng.randint(3, 40) if ftype else "/", h))
                        if left <= 0:
                            break
                path = build_timesheet(tmp / f"{name.split()[-1]}_{d.isoformat()}.xlsx", name=name, work_date=d, rows=rows)
                with session_scope() as db:
                    import_file(db, path.read_bytes(), ImportContext(filename=path.name, source="upload",
                                                                      sender_email=None))
                count += 1
        d += timedelta(days=1)
    print(f"Imported {count} demo timesheets into {home}")


if __name__ == "__main__":
    main()
