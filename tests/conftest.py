"""Test setup: every test session gets its own throw-away data folder.

TIMESHEET_HOME must be set before any backend module is imported.
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="timesheet_test_"))
os.environ["TIMESHEET_HOME"] = str(_TMP)
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.database import session as db_session  # noqa: E402
from backend.database.init_db import init_db  # noqa: E402
from backend.models import Base  # noqa: E402


@pytest.fixture()
def db():
    """Fresh database for each test."""
    settings.ensure_dirs()
    if settings.database_path.exists():
        db_session.dispose()
    engine = db_session.configure()
    Base.metadata.drop_all(engine)
    init_db()
    s = db_session.new_session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def tmp_xlsx(tmp_path):
    from scripts.make_sample_timesheet import build_timesheet

    def make(fname="sheet.xlsx", **kw):
        return build_timesheet(tmp_path / fname, **kw)
    return make
