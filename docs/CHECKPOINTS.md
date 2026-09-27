# Development checkpoints

All phases were built in one session on 2026-09-27 on the target desktop (Windows 11,
Python 3.14.6). Test suite: **29 tests, all passing** (`.venv\Scripts\python.exe -m pytest -q`).

---

## Phase 1 — Architecture + database

1. **Implemented**: configuration from `.env` with a movable data folder; SQLAlchemy models; engine holder that can be recreated (restore/tests); table creation; default categories, keyword rules and runtime settings.
2. **Files created**: `backend/config.py`, `backend/models/__init__.py`, `backend/database/{__init__,session,init_db}.py`, `backend/services/app_settings.py`.
3. **Files changed**: —
4. **How it works**: `TIMESHEET_HOME` (or per-folder overrides) decides where `data/`, `backups/`, `reports/`, `imports/`, `logs/`, `secrets/` live. SQLite runs in WAL mode with foreign keys. `DATABASE_URL` can point to PostgreSQL later.
5. **Tests**: fixtures create a fresh database per test in a temporary folder.
6. **Results**: pass (exercised by every other test).
7. **Limitations**: no Alembic migrations; new tables are auto-created, but column changes would need a migration.
8. **Next**: Excel importer.

## Phase 2 — Excel importer

1. **Implemented**: header-based parser, label-based name/date, total-row check, validation with data-quality issues, employee matching (aliases, honorifics, sender email, auto-create), date fallbacks, duplicate/resubmission handling, note-line classification with estimated hour allocation.
2. **Files created**: `backend/excel/{parser,validator}.py`, `backend/services/{importer,classifier,employees}.py`, `scripts/make_sample_timesheet.py`, `tests/test_parser.py`, `tests/test_importer.py`.
3. **Files changed**: parser (after tests: an empty Name cell must not pick up the sheet title or header text); classifier (plurals; weak keywords defer to the heading).
4. **How it works**: see ARCHITECTURE.md → Import pipeline.
5. **Tests**: real-layout replica of the provided sheet; shifted and re-ordered columns; non-timesheet files; bad values; duplicates; resubmissions; honorific matching; heading inheritance.
6. **Results**: pass. The real example yields 1 entry, 16 activity lines, 10.4 h, categories: Order Processing, Material & Shortage, Purchasing & Vendors, Communication, Administrative, Quality & RMA, Data Entry & Reporting, Coordination.
7. **Limitations**: `.xls` unsupported; hours split evenly across lines (estimate); keyword rules need tuning to your team's vocabulary (editable in Settings).
8. **Next**: Gmail.

## Phase 3 — Gmail integration

1. **Implemented**: read-only Gmail client, OAuth desktop flow, sync with look-back window, allowed-senders filter, processed-message table, per-message transaction, job log.
2. **Files created**: `backend/gmail/{client,sync}.py`, `backend/services/jobs.py`, `scripts/gmail_auth.{py,bat}`, `tests/fake_gmail.py`, `tests/test_gmail_sync.py`.
3. **Files changed**: —
4. **How it works**: lists messages matching the query + `after:` date, skips known IDs, downloads Excel attachments, saves them, imports them, records the message. Failures leave the message unrecorded so the next run retries.
5. **Tests**: simulated Gmail API (messages, attachments): import, re-sync (no re-import), forwarded identical file (duplicate), sender filter, "not configured".
6. **Results**: pass. **Not tested against your real Gmail** (needs your OAuth client; see GMAIL_SETUP.md).
7. **Limitations**: "Testing" OAuth apps expire after 7 days (documented); no Gmail labels applied (read-only by design).
8. **Next**: KPI engine.

## Phase 4 — KPI engine

1. **Implemented**: summaries, category distribution, daily/weekly series, weekly category share, repeated activities, missing timesheets, data quality, previous-period baseline and comparison, hour anomalies, category shifts, factual alerts.
2. **Files created**: `backend/analytics/{kpi,alerts}.py`, `tests/test_kpi.py`.
3. **Files changed**: —
4. **How it works**: computed on demand from stored rows; see ARCHITECTURE.md → KPIs.
5. **Tests**: two employees over two weeks with known values; anomaly (13.5 h vs 8 h average); pending-vs-missing around the deadline; alert wording contains no judgements.
6. **Results**: pass.
7. **Limitations**: no productivity score by design; anomalies need ≥ 5 prior submitted days.
8. **Next**: web dashboard.

## Phases 5–7 — Web dashboard, employee analytics, reports

1. **Implemented**: JSON API for every page; single-page UI (Dashboard, Employees + detail, Timesheets, Analytics, Reports, Imports, Settings); dependency-free SVG charts; daily report with xlsx/csv/pdf export, scheduled saving.
2. **Files created**: `backend/api/*.py`, `backend/reports/daily.py`, `backend/main.py`, `run_server.py`, `frontend/**`, `scripts/seed_demo.py`, `tests/test_api.py`.
3. **Files changed**: page layouts after reviewing them in the browser (charts full-width so labels stay legible; nowrap on first column).
4. **How it works**: FastAPI serves `/api/*` and the static UI from the same port; the UI uses hash routing and fetch.
5. **Tests**: API tests for every page's endpoint; export magic bytes (PK / %PDF / BOM); in-browser review of every page against 154 demo timesheets (4 people × 8 weeks).
6. **Results**: pass; pages rendered without console errors.
7. **Limitations**: charts are single-series by design (categories shown as labelled bars / heatmap, not colours).
8. **Next**: authentication.

## Phase 8 — Authentication

1. **Implemented**: first-run admin creation (desktop only), login/logout, scrypt hashing, server-side sessions, roles (admin/manager/viewer), throttling, CSRF defences, security headers, access log, user management, password change/reset.
2. **Files created**: `backend/auth/{security,deps}.py`, `backend/api/auth.py`, `frontend/pages/login.js`, `scripts/create_admin.py`.
3. **Files changed**: `backend/main.py` (middleware).
4. **How it works**: see ARCHITECTURE.md → Security.
5. **Tests**: every route rejects anonymous requests; setup refused remotely and after first use; weak password refused; CSRF header/Origin enforcement; cookie flags; throttle (429); viewer cannot mutate; remote requests logged.
6. **Results**: pass.
7. **Limitations**: no 2FA (Tailscale device authentication is the second factor for remote access); throttle state resets on restart.
8. **Next**: remote access.

## Phase 9 — Remote access

1. **Implemented**: Tailscale Serve design (evaluated against Cloudflare Tunnel), setup script, proxy-aware client detection (trusts forwarding headers only from 127.0.0.1), Secure cookies + HSTS over HTTPS, optional LAN firewall rule.
2. **Files created**: `scripts/setup_tailscale.ps1`, `scripts/allow_lan_firewall.ps1`, `docs/REMOTE_ACCESS.md`.
3. **Files changed**: `backend/auth/security.py`.
4. **How it works**: see REMOTE_ACCESS.md.
5. **Tests**: simulated Tailscale client (100.x address, ts.net host) sees the same data and is logged as "tailscale"; scripts syntax-checked.
6. **Results**: pass. **Real Tailscale not tested** (needs your account).
7. **Limitations**: remote devices need the Tailscale app.
8. **Next**: automation.

## Phase 10 — Automation + Windows startup

1. **Implemented**: in-process scheduler (Gmail, backup, report, cleanup), startup catch-up, backup/restore with validation and safety copy, `start.bat`, `stop.bat`, scheduled-task installer (sign-in or boot), hidden-mode console logging.
2. **Files created**: `backend/services/{scheduler,backup}.py`, `start.bat`, `stop.bat`, `scripts/{install_startup,uninstall_startup,stop_server,_common}.ps1`.
3. **Files changed**: `run_server.py` (pythonw support).
4. **How it works**: see OPERATIONS.md.
5. **Tests**: backup → change → restore (data reverted, pre-restore copy made, bad name rejected); launched hidden with `pythonw.exe` on a scratch data folder: health OK, catch-up produced a backup and 4 missed reports; stop script stopped it; restarted: only the Gmail check ran again.
6. **Results**: pass. **Scheduled task not installed and no reboot performed** (changes your Windows configuration; run it yourself).
7. **Limitations**: a sleeping PC is an offline server (set Sleep: Never).
8. **Next**: tests + docs.

## Phase 11 — Testing + deployment documentation

1. **Implemented**: end-to-end acceptance test, README, architecture, remote access, Gmail setup, operations, acceptance checklist.
2. **Files created**: `tests/test_acceptance.py`, `README.md`, `docs/*.md`, `.env.example`, `.gitignore`, `requirements.txt`.
3. **Files changed**: —
4. **How it works**: —
5. **Tests**: full suite.
6. **Results**: 29 passed.
7. **Limitations**: manual items in ACCEPTANCE_TESTS.md remain for you to run.
8. **Next**: your setup — Gmail, Tailscale, startup task, first real timesheets; tune keyword rules.
