from sqlalchemy import select

from backend.gmail.sync import sync_gmail
from backend.models import GmailMessage, JobRun, Submission, TimesheetEntry
from backend.services import app_settings
from tests.fake_gmail import FakeGmail


def test_sync_imports_and_skips_duplicates(db, tmp_xlsx):
    content = tmp_xlsx("Kamrul.xlsx").read_bytes()
    gm = FakeGmail()
    gm.add_message("m1", "kamrul@camco.example", "Timesheet 9/23", [("Kamrul_0923.xlsx", content)])
    gm.add_message("m2", "someone@camco.example", "Lunch?", [])

    s1 = sync_gmail("manual", service=gm)
    assert s1["status"] == "ok", s1
    assert s1["files_imported"] == 1 and s1["new_messages"] == 2
    assert "after:" in gm.list_calls[0]
    sub = db.scalar(select(Submission))
    assert sub.source == "gmail" and sub.gmail_message_id == "m1" and sub.sender_email == "kamrul@camco.example"
    assert sub.stored_path and sub.import_status.startswith("imported")

    # Test 10: running again must not import the same email twice
    s2 = sync_gmail("manual", service=gm)
    assert s2["new_messages"] == 0 and s2["files_imported"] == 0
    assert db.query(TimesheetEntry).count() == 1

    # Same file forwarded in a different email -> duplicate, not imported
    gm.add_message("m3", "boss@camco.example", "Fwd: Timesheet", [("copy.xlsx", content)])
    s3 = sync_gmail("manual", service=gm)
    assert s3["duplicates"] == 1
    assert db.query(TimesheetEntry).count() == 1
    assert db.query(GmailMessage).count() == 3
    assert db.query(JobRun).filter_by(job="gmail_sync").count() == 3


def test_allowed_senders_filter(db, tmp_xlsx):
    app_settings.set_value(db, "gmail_allowed_senders", "@camco.example"); db.commit()
    gm = FakeGmail()
    gm.add_message("x1", "spam@evil.example", "Invoice", [("t.xlsx", tmp_xlsx().read_bytes())])
    s = sync_gmail("manual", service=gm)
    assert s["files_imported"] == 0
    assert db.scalar(select(GmailMessage)).status == "skipped"


def test_not_configured(db):
    s = sync_gmail("manual")
    assert s["status"] == "not_configured"
