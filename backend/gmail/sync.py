"""Gmail -> importer synchronisation.

Runs every N minutes (scheduler), on startup, and from the "Sync Gmail Now" button.
Each run looks back GMAIL_LOOKBACK_DAYS, so anything that arrived while the
desktop was off is picked up automatically when it starts again. Messages
already in the gmail_messages table are skipped, so nothing is imported twice.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from backend.database.session import session_scope
from backend.gmail.client import GmailClient, GmailNotConfigured
from backend.models import GmailMessage
from backend.services import app_settings
from backend.services.importer import EXCEL_EXTENSIONS, ImportContext, import_file, store_file
from backend.services.jobs import record_job

log = logging.getLogger(__name__)
_sync_lock = threading.Lock()

TIMESHEET_LIKE = EXCEL_EXTENSIONS | {".xls"}  # .xls is recorded as a failed import with a clear message


def _sender_allowed(sender: str | None, allowed: str) -> bool:
    rules = [r.strip().lower() for r in allowed.split(",") if r.strip()]
    if not rules:
        return True
    sender = (sender or "").lower()
    return any(sender == r or (r.startswith("@") and sender.endswith(r)) for r in rules)


def sync_gmail(trigger: str = "schedule", service=None) -> dict:
    """Returns a summary dict. Only one sync runs at a time."""
    if not _sync_lock.acquire(blocking=False):
        return {"status": "busy", "message": "A Gmail sync is already running."}
    try:
        summary = {"status": "ok", "messages_checked": 0, "new_messages": 0, "files_imported": 0,
                   "duplicates": 0, "failed": 0, "errors": [], "message": ""}
        try:
            with record_job("gmail_sync", trigger) as job:
                try:
                    client = GmailClient(service)
                except GmailNotConfigured as exc:
                    summary.update(status="not_configured", message=str(exc))
                    job.status, job.message = "error", str(exc)
                    return summary
                _run(client, summary)
                job.message = summary["message"]
                if summary["errors"]:
                    job.status = "error"
                    job.message += " Errors: " + "; ".join(summary["errors"][:5])
        except Exception as exc:  # noqa: BLE001 - already logged by record_job
            summary.update(status="error", message=f"Gmail sync failed: {exc}")
        return summary
    finally:
        _sync_lock.release()


def _run(client: GmailClient, summary: dict) -> None:
    with session_scope() as db:
        query = app_settings.get(db, "gmail_query")
        lookback = app_settings.get_int(db, "gmail_lookback_days", 14)
        allowed = app_settings.get(db, "gmail_allowed_senders")
    after = (date.today() - timedelta(days=lookback)).strftime("%Y/%m/%d")
    ids = client.list_message_ids(f"{query} after:{after}")
    summary["messages_checked"] = len(ids)

    with session_scope() as db:
        seen = set(db.scalars(select(GmailMessage.gmail_message_id).where(GmailMessage.gmail_message_id.in_(ids)))) if ids else set()

    for message_id in reversed(ids):  # oldest first, so resubmissions replace in the right order
        if message_id in seen:
            continue
        try:
            _process_message(client, message_id, allowed, summary)
        except Exception as exc:  # noqa: BLE001 - leave unrecorded so the next run retries it
            log.exception("Failed to process Gmail message %s", message_id)
            summary["errors"].append(f"{message_id}: {exc}")

    summary["message"] = (
        f"Checked {summary['messages_checked']} message(s), {summary['new_messages']} new; "
        f"imported {summary['files_imported']} file(s), {summary['duplicates']} duplicate(s), {summary['failed']} failed."
    )


def _process_message(client: GmailClient, message_id: str, allowed: str, summary: dict) -> None:
    info = client.get_message(message_id)
    summary["new_messages"] += 1
    excel = [a for a in info.attachments if Path(a.filename).suffix.lower() in TIMESHEET_LIKE]

    with session_scope() as db:
        record = GmailMessage(
            gmail_message_id=info.message_id, thread_id=info.thread_id, sender=info.sender_email,
            subject=info.subject, email_timestamp=info.timestamp, attachments_found=len(excel),
        )
        if not _sender_allowed(info.sender_email, allowed):
            record.status, record.note = "skipped", "Sender is not in the allowed senders list."
            db.add(record)
            return
        if not excel:
            record.status = "no_attachment"
            db.add(record)
            return

        for att in excel:
            content = client.download(info.message_id, att)
            stored = store_file(content, att.filename, prefix=info.message_id)
            ctx = ImportContext(
                filename=att.filename, source="gmail", gmail_message_id=info.message_id,
                sender_email=info.sender_email, subject=info.subject, email_timestamp=info.timestamp,
            )
            for sub in import_file(db, content, ctx, stored):
                if sub.import_status == "duplicate":
                    summary["duplicates"] += 1
                elif sub.import_status == "failed":
                    summary["failed"] += 1
                else:
                    summary["files_imported"] += 1
            db.flush()
        db.add(record)  # committed together with the imports: all or nothing per message
