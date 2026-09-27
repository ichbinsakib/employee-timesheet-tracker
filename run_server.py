"""Start the Timesheet Tracker server (API + web UI + Gmail/backup/report scheduler).

    python run_server.py

Host/port come from .env (TIMESHEET_HOST / TIMESHEET_PORT).
"""
import socket
import sys

import uvicorn

from backend.config import settings


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    if sys.stdout is None or sys.stderr is None:  # started hidden with pythonw.exe (Windows startup task)
        settings.ensure_dirs()
        console = open(settings.logs_dir / "server-console.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or console
        sys.stderr = sys.stderr or console
    if port_in_use(settings.port):
        print(f"Port {settings.port} is already in use - the Timesheet Tracker is probably already running.")
        print(f"Open http://localhost:{settings.port}")
        sys.exit(0)
    print(f"Timesheet Tracker: open http://localhost:{settings.port}  (data: {settings.data_dir})", flush=True)
    uvicorn.run(
        "backend.main:app", host=settings.host, port=settings.port, workers=1,
        proxy_headers=False,  # we decide ourselves when to trust X-Forwarded-* (only from 127.0.0.1)
        log_level="info", access_log=False,
    )
