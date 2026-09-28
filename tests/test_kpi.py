from datetime import date, datetime, timedelta

from backend.analytics import alerts, kpi
from backend.models import Employee
from backend.services.importer import ImportContext, import_file

MON = date(2026, 9, 14)  # a Monday


def _add(db, tmp_xlsx, name, day, rows):
    p = tmp_xlsx(f"{name}_{day}.xlsx", name=name, work_date=day, rows=rows)
    import_file(db, p.read_bytes(), ImportContext(filename=p.name)); db.commit()


def _seed(db, tmp_xlsx):
    db.add(Employee(name="Alice Admin", tracking_start=MON - timedelta(days=7)))
    db.add(Employee(name="Bob Builder", tracking_start=MON))
    db.commit()
    for i in range(10):  # two weeks of weekdays
        d = MON + timedelta(days=i + (i // 5) * 2)
        _add(db, tmp_xlsx, "Alice Admin", d, [
            ("P1", "-Approve the invoice\n-Teams & email follow up", "/", "Yes", "/", 4),
            ("P2", "Drawing of bracket assembly", "Drawing", "No", 10, 4),
        ])
        if i != 3:  # Bob misses Thursday of week 1
            _add(db, tmp_xlsx, "Bob Builder", d, [("P3", "Model updates", "Model", "Yes", 5, 13.5 if i == 9 else 8)])


def test_summary_and_distribution(db, tmp_xlsx):
    _seed(db, tmp_xlsx)
    cats = kpi.codes(db)
    ds = kpi.load(db, MON, MON + timedelta(days=11))
    alice = db.query(Employee).filter_by(name="Alice Admin").one()
    s = kpi.summarize(ds, cats, alice.id)
    assert s["total_hours"] == 80 and s["days_submitted"] == 10 and s["avg_daily_hours"] == 8
    assert s["task_count"] == 20 and s["completed_tasks"] == 10 and s["incomplete_tasks"] == 10
    assert s["completion_rate"] == 50.0 and s["avg_hours_per_task"] == 4
    assert s["feature_total"] == 100 and s["hours_per_feature"] == 0.4
    # grouped by the rows' own costing codes, using recorded hours
    assert {(c["code"], c["hours"], c["tasks"], c["percent"]) for c in s["codes"]} == {("P1", 40, 10, 50.0), ("P2", 40, 10, 50.0)}
    assert s["codes_used"] == 2


def test_missing_and_status(db, tmp_xlsx):
    _seed(db, tmp_xlsx)
    now = datetime(2026, 9, 25, 20, 0)
    missing = kpi.missing_timesheets(db, MON, date(2026, 9, 25), now=now)
    bob = [m for m in missing if m["employee"] == "Bob Builder"]
    assert [m["date"] for m in bob] == ["2026-09-17"]
    alice = [m for m in missing if m["employee"] == "Alice Admin"]
    assert alice == []  # Alice submitted every weekday in the range


def test_anomalies_and_alerts(db, tmp_xlsx):
    _seed(db, tmp_xlsx)
    last = date(2026, 9, 25)
    anomalies = kpi.daily_hours_anomalies(db, MON, last)
    bob = [a for a in anomalies if a["employee"] == "Bob Builder"]
    assert bob and bob[0]["hours"] == 13.5 and bob[0]["recent_average"] == 8
    out = alerts.build_alerts(db, last, lookback_days=14, now=datetime(2026, 9, 25, 20, 0))
    kinds = {a["type"] for a in out}
    assert {"missing", "unusual_hours", "incomplete", "gmail"} <= kinds
    text = " ".join(a["message"] for a in out).lower()
    for judgement in ("unproductive", "poor", "lazy", "score"):
        assert judgement not in text
    msg = next(a["message"] for a in out if a["type"] == "unusual_hours")
    assert msg == "Bob Builder recorded 13.5 hours on 2026-09-25. Recent average: 8 hours."


def test_code_shift():
    cur = {"total_hours": 40, "codes": [{"code": "P1", "label": "P1 – A", "percent": 45}, {"code": "P2", "label": "P2 – B", "percent": 55}]}
    base = {"total_hours": 40, "codes": [{"code": "P1", "label": "P1 – A", "percent": 20}, {"code": "P2", "label": "P2 – B", "percent": 80}]}
    shifts = kpi.code_shifts(cur, base)
    assert {s["code"] for s in shifts} == {"P1", "P2"} and shifts[0]["label"].startswith("P")


def test_day_status_pending_vs_missing(db, tmp_xlsx):
    _seed(db, tmp_xlsx)
    day = date(2026, 9, 28)  # Monday with no submissions
    before = kpi.day_status(db, day, now=datetime(2026, 9, 28, 10, 0))
    assert before["expected"] == 2 and len(before["pending"]) == 2 and not before["missing"]
    after = kpi.day_status(db, day, now=datetime(2026, 9, 28, 19, 0))
    assert len(after["missing"]) == 2


def test_zero_hour_rows_are_not_tasks(db, tmp_xlsx):
    _add(db, tmp_xlsx, "Zed Zero", MON, [("P1", "Worked item", "/", "/", "/", 6), ("P2", "Standing item", "/", "/", "/", 0),
                                         ("P3", "Another standing item", "/", "/", "/", 0)])
    s = kpi.summarize(kpi.load(db, MON, MON), kpi.codes(db))
    assert s["task_count"] == 1 and s["zero_hour_rows"] == 2
    assert s["avg_hours_per_task"] == 6 and s["total_hours"] == 6


def test_upgrade_adds_new_category_rules_without_touching_edits(db):
    from backend.database.init_db import seed_defaults
    from backend.models import ClassificationRule, WorkCategory
    hr = db.query(WorkCategory).filter_by(name="HR & Payroll").one()
    # simulate a database created before the category existed, with a user-edited rule
    db.query(ClassificationRule).filter_by(category_id=hr.id).delete()
    db.delete(hr)
    rule = db.query(ClassificationRule).filter_by(keyword="kanban").one()
    rule.priority = 99
    db.commit()
    seed_defaults()
    db.expire_all()
    hr = db.query(WorkCategory).filter_by(name="HR & Payroll").one()
    assert db.query(ClassificationRule).filter_by(category_id=hr.id, keyword="payroll").count() == 1
    assert db.query(ClassificationRule).filter_by(keyword="kanban").one().priority == 99
