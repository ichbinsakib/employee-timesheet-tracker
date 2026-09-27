"""End-to-end version of the acceptance tests that can run offline.

Gmail is simulated (tests/fake_gmail.py) and "another network" is simulated with a
client that has a non-local IP and host name. Real Gmail and real Tailscale access
are checked by hand; see docs/ACCEPTANCE_TESTS.md.
"""
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.database import session as db_session
from backend.gmail.sync import sync_gmail
from backend.main import app
from backend.models import JobRun, Submission
from backend.services import scheduler
from tests.fake_gmail import FakeGmail

H = {"X-Requested-With": "timesheet-app"}
PW = "Acceptance1Password"
DAY = "2026-09-23"


def test_end_to_end(db, tmp_xlsx, tmp_path):
    gm = FakeGmail()
    # Test 1: employee emails an Excel timesheet (the real example layout)
    content = tmp_xlsx().read_bytes()
    gm.add_message("msg-1", "kamrul@camco.example", "Timesheet 9/23", [("Kamrul Hasan 9-23-2026.xlsx", content)])

    # Tests 2-6: desktop detects it, downloads, parses, validates, stores
    result = sync_gmail("schedule", service=gm)
    assert result["files_imported"] == 1, result
    sub = db.scalar(select(Submission))
    assert sub.import_status.startswith("imported") and sub.work_date == date(2026, 9, 23)
    assert Path(sub.stored_path).exists()  # the original file was saved on the desktop

    with TestClient(app, base_url="http://localhost:8000", client=("127.0.0.1", 1)) as local, \
         TestClient(app, base_url="https://desk.tail1234.ts.net", client=("100.101.102.103", 2)) as remote:
        local.post("/api/auth/setup", json={"username": "admin", "password": PW}, headers=H)

        # Tests 7-8: KPIs calculated, dashboard shows them
        dash = local.get("/api/dashboard", params={"date": DAY}).json()
        assert dash["today"]["submitted"] == 1 and dash["today"]["total_hours"] == 10.4
        assert dash["employees"][0]["tasks"] == 1
        assert sum(c["percent"] for c in dash["distribution"]) > 99

        # Test 9: daily report generated (xlsx/csv/pdf saved to the reports folder)
        files = local.post("/api/reports/generate", params={"date": DAY}, headers=H).json()["files"]
        assert sorted(f.rsplit(".", 1)[1] for f in files) == ["csv", "pdf", "xlsx"]

        # Test 10: the same email is not imported twice, nor the same file in a new email
        assert sync_gmail("schedule", service=gm)["new_messages"] == 0
        gm.add_message("msg-2", "boss@camco.example", "Fwd: Timesheet", [("copy.xlsx", content)])
        assert sync_gmail("schedule", service=gm)["duplicates"] == 1
        assert local.get("/api/timesheets", params={"end": DAY}).json()["total"] == 1

        # Tests 11-13: local and "other network" clients see the same database
        assert remote.post("/api/auth/login", json={"username": "admin", "password": PW}, headers=H).status_code == 200
        r_dash = remote.get("/api/dashboard", params={"date": DAY}).json()
        assert r_dash["today"] == local.get("/api/dashboard", params={"date": DAY}).json()["today"]
        via = local.get("/api/settings/access-log", params={"remote_only": True}).json()
        assert any(x["via"] == "tailscale" and x["ip"] == "100.101.102.103" for x in via)

    # Test 14: "restart" — engine disposed and recreated, catch-up runs, data still there, no duplicates
    db_session.dispose()
    db_session.configure()
    scheduler.catch_up()
    with db_session.session_scope() as s:
        assert s.query(Submission).filter(Submission.import_status.like("imported%")).count() == 1
        assert s.scalar(select(JobRun).where(JobRun.trigger == "startup", JobRun.job == "backup")) is not None
