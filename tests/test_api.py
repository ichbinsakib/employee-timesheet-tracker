import pytest
from fastapi.testclient import TestClient

from backend.main import app

H = {"X-Requested-With": "timesheet-app"}
PW = "Str0ngPassword"


@pytest.fixture()
def local(db):
    with TestClient(app, base_url="http://localhost:8000", client=("127.0.0.1", 50000)) as c:
        yield c


@pytest.fixture()
def remote(db):
    """Simulates a browser on another machine (LAN)."""
    with TestClient(app, base_url="http://192.168.1.50:8000", client=("192.168.1.77", 50000)) as c:
        yield c


def _setup_admin(c):
    r = c.post("/api/auth/setup", json={"username": "admin", "password": PW}, headers=H)
    assert r.status_code == 200, r.text


def test_routes_require_login(local):
    for path in ("/api/dashboard", "/api/employees", "/api/timesheets", "/api/analytics", "/api/reports/daily", "/api/imports/submissions", "/api/settings"):
        assert local.get(path).status_code == 401, path
    assert local.get("/").status_code == 200  # the login page itself is public


def test_first_run_setup_only_from_desktop(remote, local):
    assert remote.get("/api/auth/status").json()["can_setup_here"] is False
    assert remote.post("/api/auth/setup", json={"username": "admin", "password": PW}, headers=H).status_code == 403
    st = local.get("/api/auth/status").json()
    assert st["setup_required"] and st["can_setup_here"]
    assert local.post("/api/auth/setup", json={"username": "admin", "password": "weak"}, headers=H).status_code == 400
    _setup_admin(local)
    assert local.post("/api/auth/setup", json={"username": "x2", "password": PW}, headers=H).status_code == 409


def test_login_logout_and_csrf(local, remote):
    _setup_admin(local)
    assert remote.post("/api/auth/login", json={"username": "admin", "password": PW}).status_code == 403  # no header
    assert remote.post("/api/auth/login", json={"username": "admin", "password": PW},
                       headers=H | {"Origin": "https://evil.example"}).status_code == 403
    assert remote.post("/api/auth/login", json={"username": "admin", "password": "nope"}, headers=H).status_code == 401
    r = remote.post("/api/auth/login", json={"username": "admin", "password": PW}, headers=H)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert remote.get("/api/dashboard").status_code == 200
    remote.post("/api/auth/logout", headers=H)
    assert remote.get("/api/dashboard").status_code == 401


def test_login_throttle(remote, local):
    _setup_admin(local)
    for _ in range(5):
        remote.post("/api/auth/login", json={"username": "admin", "password": "bad"}, headers=H)
    r = remote.post("/api/auth/login", json={"username": "admin", "password": PW}, headers=H)
    assert r.status_code == 429
    from backend.auth.security import throttle
    throttle._fails.clear()


def test_upload_dashboard_report_flow(local, tmp_xlsx):
    _setup_admin(local)
    path = tmp_xlsx("Kamrul_2026-09-23.xlsx")
    with open(path, "rb") as fh:
        r = local.post("/api/imports/upload", files={"file": (path.name, fh, "application/octet-stream")}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()[0]["status"].startswith("imported")
    dash = local.get("/api/dashboard", params={"date": "2026-09-23"}).json()
    assert dash["today"]["total_hours"] == 10.4 and dash["today"]["submitted"] == 1
    assert dash["employees"][0]["employee"] == "Md. Kamrul Hasan"
    emp_id = dash["employees"][0]["employee_id"]
    detail = local.get(f"/api/employees/{emp_id}", params={"end": "2026-09-23"}).json()
    assert detail["summary"]["total_hours"] == 10.4 and detail["recent_entries"]
    entries = local.get("/api/timesheets", params={"end": "2026-09-23"}).json()
    assert entries["total"] == 1
    assert local.get(f"/api/timesheets/{entries['items'][0]['id']}").json()["code_label"] == "P4627 – Co-ordination task (from notes)"
    rep = local.get("/api/reports/daily", params={"date": "2026-09-23"}).json()
    assert rep["summary"]["total_hours"] == 10.4
    for fmt, magic in (("xlsx", b"PK"), ("pdf", b"%PDF"), ("csv", b"\xef\xbb\xbf")):
        r = local.get("/api/reports/daily/export", params={"date": "2026-09-23", "fmt": fmt})
        assert r.status_code == 200 and r.content.startswith(magic), fmt
    gen = local.post("/api/reports/generate", params={"date": "2026-09-23"}, headers=H)
    assert gen.status_code == 200 and len(gen.json()["files"]) == 3
    assert len(local.get("/api/reports").json()) == 3
    # remote access is logged
    an = local.get("/api/analytics", params={"end": "2026-09-23"}).json()
    assert an["summary"]["total_hours"] == 10.4


def test_viewer_cannot_change_things(local):
    _setup_admin(local)
    assert local.post("/api/settings/users", json={"username": "viewer1", "password": PW, "role": "viewer"}, headers=H).status_code == 200
    local.post("/api/auth/logout", headers=H)
    local.post("/api/auth/login", json={"username": "viewer1", "password": PW}, headers=H)
    assert local.get("/api/dashboard").status_code == 200
    assert local.post("/api/imports/sync", headers=H).status_code == 403
    assert local.post("/api/settings/backups", headers=H).status_code == 403
    assert local.put("/api/settings", json={"holidays": ""}, headers=H).status_code == 403


def test_backup_and_restore(local, tmp_xlsx):
    _setup_admin(local)
    b = local.post("/api/settings/backups", headers=H)
    assert b.status_code == 200
    name = b.json()["name"]
    # add data after the backup
    with open(tmp_xlsx(), "rb") as fh:
        local.post("/api/imports/upload", files={"file": ("a.xlsx", fh)}, headers=H)
    assert local.get("/api/timesheets", params={"end": "2026-09-30", "days": 60}).json()["total"] == 1
    assert local.post("/api/settings/backups/restore", json={"name": name, "confirm": "yes"}, headers=H).status_code == 400
    r = local.post("/api/settings/backups/restore", json={"name": name, "confirm": "RESTORE"}, headers=H)
    assert r.status_code == 200, r.text
    assert "pre-restore" in r.json()["safety_backup"]
    assert local.get("/api/timesheets", params={"end": "2026-09-30", "days": 60}).json()["total"] == 0
    assert any(x["kind"] == "pre-restore" for x in local.get("/api/settings/backups").json()["backups"])
    assert local.post("/api/settings/backups/restore", json={"name": "../../etc.db", "confirm": "RESTORE"}, headers=H).status_code == 400


def test_remote_requests_are_logged(local, remote):
    _setup_admin(local)
    remote.post("/api/auth/login", json={"username": "admin", "password": PW}, headers=H)
    remote.get("/api/dashboard")
    log = local.get("/api/settings/access-log", params={"remote_only": True}).json()
    events = {(x["event"], x["via"]) for x in log}
    assert ("login_ok", "lan") in events and ("request", "lan") in events
