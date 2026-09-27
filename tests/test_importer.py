from datetime import date

from sqlalchemy import select

from backend.models import Employee, Submission, TimesheetEntry, WorkCategory
from backend.services.importer import ImportContext, import_file


def _imp(db, path, **kw):
    subs = import_file(db, path.read_bytes(), ImportContext(filename=path.name, **kw))
    db.commit()
    return subs


def test_import_real_example(db, tmp_xlsx):
    subs = _imp(db, tmp_xlsx("Kamrul.xlsx"), sender_email="kamrul@example.com")
    assert len(subs) == 1
    sub = subs[0]
    assert sub.import_status in ("imported", "imported_with_warnings"), sub.error_message
    assert sub.work_date == date(2026, 9, 23)
    assert sub.total_hours == 10.4
    emp = db.get(Employee, sub.employee_id)
    assert emp.name == "Md. Kamrul Hasan" and emp.auto_created and emp.email == "kamrul@example.com"
    entry = db.scalar(select(TimesheetEntry))
    assert entry.title == "Co-ordination task"
    assert len(entry.activities) == 16
    assert abs(sum(a.allocated_hours for a in entry.activities) - 10.4) < 1e-6
    cats = {db.get(WorkCategory, a.category_id).name for a in entry.activities}
    assert {"Order Processing", "Material & Shortage", "Purchasing & Vendors", "Communication", "Coordination", "Administrative", "Quality & RMA"} <= cats
    assert db.get(WorkCategory, entry.primary_category_id).name == "Coordination"


def test_duplicate_file_not_imported_twice(db, tmp_xlsx):
    p = tmp_xlsx("a.xlsx")
    _imp(db, p)
    second = _imp(db, p)[0]
    assert second.import_status == "duplicate"
    assert db.query(TimesheetEntry).count() == 1


def test_resubmission_replaces_earlier(db, tmp_xlsx):
    _imp(db, tmp_xlsx("a.xlsx"))
    newer = _imp(db, tmp_xlsx("b.xlsx", rows=[("P4627", "-SO Release\n-Kanban checking", "/", "Yes", "/", 9.0)]))[0]
    assert newer.duplicate_status == "resubmission"
    assert db.query(TimesheetEntry).count() == 1
    assert db.scalar(select(TimesheetEntry)).burden_hours == 9.0
    statuses = sorted(s.import_status for s in db.scalars(select(Submission)))
    assert "superseded" in statuses


def test_matches_existing_employee_ignoring_honorific(db, tmp_xlsx):
    db.add(Employee(name="Kamrul Hasan", email="k@x.com")); db.commit()
    sub = _imp(db, tmp_xlsx())[0]
    assert db.get(Employee, sub.employee_id).name == "Kamrul Hasan"
    assert db.query(Employee).count() == 1


def test_validation_issues(db, tmp_xlsx):
    rows = [("P1", "ok", "/", "maybe", "abc", "lots"), ("P2", "Drawing of bracket", "Drawing", "Yes", 5, 30)]
    sub = _imp(db, tmp_xlsx(rows=rows, total=12))[0]
    codes = {i.code for i in sub.issues}
    assert {"bad_completed", "bad_features", "bad_hours", "invalid_hours", "total_mismatch", "short_notes"} <= codes
    assert sub.import_status == "imported_with_warnings"


def test_failed_imports(db, tmp_path, tmp_xlsx):
    bad = tmp_path / "x.xls"; bad.write_bytes(b"old")
    assert _imp(db, bad)[0].import_status == "failed"
    noname = _imp(db, tmp_xlsx(name=None))[0]
    assert noname.import_status == "failed" and "identify the employee" in noname.error_message


def test_lines_inherit_heading_category(db, tmp_xlsx):
    rows = [("P1", "Bracket assembly drawings rev B\n-Update dimensions\n-Add weld notes\n-Email vendor", "Drawing", "Yes", 4, 3)]
    _imp(db, tmp_xlsx(rows=rows))
    entry = db.scalar(select(TimesheetEntry))
    names = [db.get(WorkCategory, a.category_id).name for a in sorted(entry.activities, key=lambda a: a.position)]
    assert names == ["Design & Engineering", "Design & Engineering", "Purchasing & Vendors"]  # "vendor" outranks "email"
