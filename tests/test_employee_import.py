from openpyxl import Workbook

from backend.models import Employee
from backend.services.employee_import import EmployeeImportError, import_employees
from tests.test_api import H, _setup_admin, local  # noqa: F401  (fixture)

CSV = (
    "full_name,email,department,designation,status\n"
    "Kamrul Hasan,kamrul@example.com,Operations,Coordinator,active\n"
    "Jane Roe,jane@example.com,Engineering,Designer,on_leave\n"
    "Old Timer,old@example.com,Engineering,Drafter,terminated\n"
    ",nobody@example.com,,,active\n"
    "Bad Mail,not-an-email,,,active\n"
).encode()


def test_csv_import_creates_updates_and_keeps_alias(db):
    db.add(Employee(name="Md. Kamrul Hasan", auto_created=True))
    db.commit()
    r = import_employees(db, CSV, "hr.csv")
    db.commit()
    assert r.rows == 5
    assert r.created == ["Jane Roe"]  # on_leave still counts as an active employee
    assert r.updated[0]["name"] == "Kamrul Hasan"
    emp = db.query(Employee).filter_by(email="kamrul@example.com").one()
    assert emp.name == "Kamrul Hasan" and "Md. Kamrul Hasan" in emp.aliases
    assert emp.department == "Operations" and emp.job_title == "Coordinator" and not emp.auto_created
    assert db.query(Employee).filter_by(name="Old Timer").count() == 0  # terminated people are never added
    reasons = " ".join(s["reason"] for s in r.skipped)
    assert "No name" in reasons and "not a valid email" in reasons and "terminated" in reasons
    # second import of the same file changes nothing
    again = import_employees(db, CSV, "hr.csv")
    assert not again.created and not again.updated and sorted(again.unchanged) == ["Jane Roe", "Kamrul Hasan"]


def test_deactivate_existing_and_xlsx(db, tmp_path):
    db.add(Employee(name="Old Timer", email="old@example.com"))
    db.commit()
    wb = Workbook(); ws = wb.active
    ws.append(["Employee Name", "E-mail", "Status", "Working days", "Expected daily hours"])
    ws.append(["Old Timer", "OLD@example.com", "Terminated", None, None])
    ws.append(["New Person", None, "Active", "Sun,Mon,Tue,Wed,Thu", 9])
    p = tmp_path / "e.xlsx"; wb.save(p)
    r = import_employees(db, p.read_bytes(), "e.xlsx")
    db.commit()
    assert r.deactivated == ["Old Timer"] and r.created == ["New Person"]
    new = db.query(Employee).filter_by(name="New Person").one()
    assert new.working_days == "Sun,Mon,Tue,Wed,Thu" and new.expected_daily_hours == 9


def test_bad_files(db):
    for content, name in ((b"a,b\n1,2\n", "x.csv"), (b"junk", "x.xlsx"), (b"x", "x.pdf")):
        try:
            import_employees(db, content, name)
            raise AssertionError("expected an error")
        except EmployeeImportError:
            pass


def test_api_preview_then_apply(local):  # noqa: F811
    _setup_admin(local)
    files = {"file": ("hr.csv", CSV, "text/csv")}
    prev = local.post("/api/employees/import", params={"apply": False}, files=files, headers=H)
    assert prev.status_code == 200 and prev.json()["applied"] is False and len(prev.json()["created"]) == 2
    assert local.get("/api/employees").json() == []  # preview saved nothing
    done = local.post("/api/employees/import", params={"apply": True}, files=files, headers=H).json()
    assert done["applied"] and sorted(done["created"]) == ["Jane Roe", "Kamrul Hasan"]
    assert len(local.get("/api/employees").json()) == 2
    bad = local.post("/api/employees/import", files={"file": ("x.csv", b"a,b\n", "text/csv")}, headers=H)
    assert bad.status_code == 400
