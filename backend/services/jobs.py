"""Record background job runs (Gmail sync, backups, reports) for the Imports/Settings pages."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from backend.database.session import session_scope
from backend.models import JobRun, now

log = logging.getLogger(__name__)


class JobResult:
    def __init__(self) -> None:
        self.message = ""
        self.status = "ok"


@contextmanager
def record_job(job: str, trigger: str) -> Iterator[JobResult]:
    with session_scope() as db:
        run = JobRun(job=job, trigger=trigger)
        db.add(run)
        db.flush()
        run_id = run.id
    result = JobResult()
    try:
        yield result
    except Exception as exc:
        log.exception("Job %s failed", job)
        result.status, result.message = "error", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        with session_scope() as db:
            run = db.get(JobRun, run_id)
            if run:
                run.finished_at = now()
                run.status = result.status
                run.message = result.message[:4000]
