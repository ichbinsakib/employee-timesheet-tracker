"""Application configuration.

All settings come from environment variables (optionally loaded from a `.env`
file in the project root). Nothing secret is hard-coded here.

Directory layout (all configurable):

    TIMESHEET_HOME            root folder for everything local (default: project dir)
    ├── data/                 SQLite database          (TIMESHEET_DATA_DIR)
    ├── backups/              database backups         (TIMESHEET_BACKUP_DIR)
    ├── reports/              generated reports        (TIMESHEET_REPORTS_DIR)
    ├── imports/              downloaded Excel files   (TIMESHEET_IMPORTS_DIR)
    ├── logs/                 application logs         (TIMESHEET_LOGS_DIR)
    └── secrets/              Gmail OAuth files        (TIMESHEET_SECRETS_DIR)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _path(env: str, default: Path) -> Path:
    value = os.getenv(env, "").strip()
    return Path(value).expanduser().resolve() if value else default


def _int(env: str, default: int) -> int:
    try:
        return int(os.getenv(env, default))
    except (TypeError, ValueError):
        return default


def _bool(env: str, default: bool) -> bool:
    value = os.getenv(env)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    home: Path = field(default_factory=lambda: _path("TIMESHEET_HOME", PROJECT_ROOT))

    def __post_init__(self) -> None:
        self.data_dir = _path("TIMESHEET_DATA_DIR", self.home / "data")
        self.backup_dir = _path("TIMESHEET_BACKUP_DIR", self.home / "backups")
        self.reports_dir = _path("TIMESHEET_REPORTS_DIR", self.home / "reports")
        self.imports_dir = _path("TIMESHEET_IMPORTS_DIR", self.home / "imports")
        self.logs_dir = _path("TIMESHEET_LOGS_DIR", self.home / "logs")
        self.secrets_dir = _path("TIMESHEET_SECRETS_DIR", self.home / "secrets")

        self.database_path = self.data_dir / "timesheets.db"
        # DATABASE_URL lets you move to PostgreSQL later without code changes.
        self.database_url = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{self.database_path.as_posix()}"

        # Web server. 0.0.0.0 = reachable on your LAN; 127.0.0.1 = this PC only
        # (Tailscale Serve still works with 127.0.0.1).
        self.host = os.getenv("TIMESHEET_HOST", "0.0.0.0")
        self.port = _int("TIMESHEET_PORT", 8000)

        # Sessions
        self.session_hours = _int("SESSION_HOURS", 12)
        # "auto" = Secure cookie whenever the request arrived over HTTPS (e.g. Tailscale Serve)
        self.cookie_secure = os.getenv("COOKIE_SECURE", "auto").strip().lower()

        # Gmail
        self.gmail_credentials_file = _path("GMAIL_CREDENTIALS_FILE", self.secrets_dir / "gmail_credentials.json")
        self.gmail_token_file = _path("GMAIL_TOKEN_FILE", self.secrets_dir / "gmail_token.json")

        # Defaults for runtime settings (editable later in the Settings page)
        self.default_gmail_query = os.getenv("GMAIL_QUERY", "has:attachment (filename:xlsx OR filename:xlsm)")
        self.default_gmail_lookback_days = _int("GMAIL_LOOKBACK_DAYS", 14)
        self.default_sync_interval_minutes = _int("GMAIL_SYNC_INTERVAL_MINUTES", 15)
        self.default_backup_interval_hours = _int("BACKUP_INTERVAL_HOURS", 24)
        self.default_backup_retention = _int("BACKUP_RETENTION", 30)
        self.default_report_time = os.getenv("DAILY_REPORT_TIME", "19:00")

        self.enable_scheduler = _bool("ENABLE_SCHEDULER", True)

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.backup_dir, self.reports_dir, self.imports_dir, self.logs_dir, self.secrets_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
