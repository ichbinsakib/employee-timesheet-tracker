"""SQLite backup and restore.

Backups use SQLite's online backup API, so they are consistent even while the
app is running. Restore always:
  1. validates the candidate file (SQLite header, integrity_check, expected tables),
  2. takes a safety backup of the current database ("pre-restore"),
  3. copies the backup into the live database through the backup API.
"""
from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from backend.config import settings
from backend.database import session as db_session

log = logging.getLogger(__name__)
_lock = threading.Lock()
REQUIRED_TABLES = {"employees", "submissions", "timesheet_entries", "users"}
NAME_RE = re.compile(r"^timesheets_(\d{4}-\d{2}-\d{2}_\d{4,6})(_[a-z-]+)?\.db$")


class BackupError(RuntimeError):
    pass


def _require_sqlite() -> None:
    if not settings.is_sqlite:
        raise BackupError("Built-in backup/restore only supports SQLite. Use your database server's backup tools.")


def create_backup(label: str = "") -> Path:
    _require_sqlite()
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    target = settings.backup_dir / f"timesheets_{stamp}{suffix}.db"
    with _lock:
        src = sqlite3.connect(settings.database_path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    log.info("Backup written to %s", target)
    return target


def list_backups() -> list[dict]:
    if not settings.backup_dir.exists():
        return []
    out = []
    for p in sorted(settings.backup_dir.glob("timesheets_*.db"), reverse=True):
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size, "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                    "kind": "pre-restore" if "pre-restore" in p.name else "manual" if "manual" in p.name else "uploaded" if "uploaded" in p.name else "automatic"})
    return out


def prune_backups(retain: int) -> int:
    """Keep the newest `retain` automatic/manual backups. Pre-restore backups are kept 3 deep."""
    removed = 0
    backups = list_backups()
    regular = [b for b in backups if b["kind"] != "pre-restore"]
    safety = [b for b in backups if b["kind"] == "pre-restore"]
    for b in regular[max(retain, 1):] + safety[3:]:
        (settings.backup_dir / b["name"]).unlink(missing_ok=True)
        removed += 1
    return removed


def resolve_backup(name: str) -> Path:
    if not NAME_RE.match(name):
        raise BackupError("Unknown backup file name.")
    path = settings.backup_dir / name
    if not path.exists():
        raise BackupError("Backup file not found.")
    return path


def validate_backup(path: Path) -> dict:
    with open(path, "rb") as fh:
        if fh.read(16) != b"SQLite format 3\x00":
            raise BackupError("File is not a SQLite database.")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        result = con.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise BackupError(f"Integrity check failed: {result}")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            raise BackupError(f"Not a timesheet database (missing tables: {', '.join(sorted(missing))}).")
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("employees", "submissions", "timesheet_entries", "users")}
    finally:
        con.close()
    return counts


def restore_backup(path: Path) -> dict:
    """Replace the live database with `path`. Caller must have confirmed with the user."""
    _require_sqlite()
    counts = validate_backup(path)
    safety = create_backup("pre-restore")
    with _lock:
        db_session.dispose()
        src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(settings.database_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        db_session.configure()
    from backend.database.init_db import init_db
    init_db()  # adds any tables introduced after the backup was taken
    log.warning("Database restored from %s (safety copy: %s)", path, safety)
    return {"restored_from": path.name, "safety_backup": safety.name, "counts": counts}


def save_uploaded_backup(content: bytes, filename: str) -> Path:
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = settings.backup_dir / f"timesheets_{stamp}_uploaded.db"
    target.write_bytes(content)
    try:
        validate_backup(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def disk_free(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return -1
