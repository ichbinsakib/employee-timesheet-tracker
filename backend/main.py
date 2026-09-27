"""FastAPI application: API + static web UI + background scheduler, in one process."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import analytics, auth, dashboard, employees, imports, reports, settings as settings_api, timesheets
from backend.auth import security
from backend.config import PROJECT_ROOT, settings
from backend.database.init_db import init_db
from backend.database.session import session_scope
from backend.models import AccessLog
from backend.services import scheduler

FRONTEND_DIR = PROJECT_ROOT / "frontend"
log = logging.getLogger("timesheet")


def setup_logging() -> None:
    settings.ensure_dirs()
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(settings.logs_dir / "app.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    root.setLevel(logging.INFO)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    init_db()
    log.info("Data folder: %s", settings.data_dir)
    if settings.enable_scheduler:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Employee Timesheet Tracker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

for r in (auth, dashboard, employees, timesheets, analytics, reports, imports, settings_api):
    app.include_router(r.router)


# --------------------------------------------------------------------------- middleware
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    # CSRF defence (in addition to SameSite=Strict cookies): state-changing API calls must
    # come from our own JavaScript (custom header) and, if the browser sends an Origin, from our own host.
    if path.startswith("/api/") and request.method not in SAFE_METHODS:
        if request.headers.get("x-requested-with") != "timesheet-app":
            return JSONResponse({"detail": "Missing request header."}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
            if urlparse(origin).netloc.lower() != host.lower():
                return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)

    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    if security.is_https(request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"

    # Log every API call that did not come from the desktop itself (LAN / Tailscale).
    if path.startswith("/api/") and not path.startswith("/api/auth/") and not security.is_local_request(request):
        try:
            user = getattr(request.state, "user", None)
            with session_scope() as db:
                db.add(AccessLog(username=user.username if user else None, ip=security.client_ip(request),
                                 via=security.access_channel(request), event="request", method=request.method,
                                 path=path[:300], status=response.status_code))
        except Exception:  # noqa: BLE001 - logging must never break a request
            log.exception("Access log write failed")
    return response


# --------------------------------------------------------------------------- web UI
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})
