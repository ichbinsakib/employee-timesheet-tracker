"""Engine / session management.

The engine lives in a small holder so it can be disposed and recreated
(database restore, tests) without restarting the process.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings

_lock = threading.RLock()
_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def configure(url: str | None = None) -> Engine:
    """(Re)create the engine. Called at startup, after a restore and by tests."""
    global _engine, _session_factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        url = url or settings.database_url
        kwargs: dict = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(_engine, "connect", _sqlite_pragmas)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
        return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure()
    return _engine  # type: ignore[return-value]


def dispose() -> None:
    with _lock:
        if _engine is not None:
            _engine.dispose()


def new_session() -> Session:
    if _session_factory is None:
        configure()
    return _session_factory()  # type: ignore[misc]


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit on success, roll back on error. For background jobs and scripts."""
    db = new_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = new_session()
    try:
        yield db
    finally:
        db.close()
