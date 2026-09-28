# Employee Timesheet Tracker

A private, self-hosted web app that turns emailed Excel timesheets into a management dashboard.

> **Your desktop owns the data. GitHub owns the code. Gmail supplies the timesheets.
> The browser provides the interface. Tailscale provides secure remote access.**

```text
Employee ──Excel──▶ Gmail ──▶ YOUR DESKTOP ─────────────────────────────────┐
                              │ Gmail sync (every 15 min, read-only)        │
                              │ Excel parser → validation → classification │
                              │ SQLite database  (data\timesheets.db)       │
                              │ KPI engine · alerts · daily reports         │
                              │ Backups · FastAPI web app (port 8000)       │
                              └─────────────────────────────────────────────┘
      Desktop browser ── http://localhost:8000 ──────────────┘         ▲
      Laptop / phone anywhere ── https://<pc>.<tailnet>.ts.net ─ Tailscale (private, HTTPS)
```

This is **not** a cloud application. The desktop is the server:

* **If the desktop is off**, the app cannot be reached and Gmail is not checked.
* **When it starts again**, the app checks the last 14 days of Gmail, takes an overdue
  backup and writes any missed daily reports — automatically.

## Quick start (on the desktop)

1. Install **Python 3.11+** (tested with 3.14) from python.org. Tick "Add python.exe to PATH".
2. Double-click **`start.bat`**. The first run creates `.venv`, installs packages and creates `.env`.
3. Open **http://localhost:8000** in Chrome and create the administrator account.
   (This first-run screen only appears on the desktop itself, never remotely.)
4. Choose where data is stored: stop the app, edit `.env`, set e.g.
   `TIMESHEET_HOME=D:\EmployeeTimesheet`, start again. See [Data location](#data-location).
5. **Connect Gmail**: follow [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md) (about 10 minutes, once).
6. **Start with Windows**: `powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1`
7. **Remote access**: follow [docs/REMOTE_ACCESS.md](docs/REMOTE_ACCESS.md) (Tailscale, about 10 minutes).

Try it with sample data first (kept completely separate from real data):

```bat
.venv\Scripts\python.exe scripts\seed_demo.py --home C:\Temp\timesheet-demo
set TIMESHEET_HOME=C:\Temp\timesheet-demo
set TIMESHEET_PORT=8765
.venv\Scripts\python.exe run_server.py
```

## What it does

| Page | What you see |
|---|---|
| **Dashboard** | Today: expected / received / missing, hours, tasks, completed / incomplete · alerts · employee overview · work distribution · trends. **Sync Gmail Now** button. |
| **Employees** | Everyone, editable (email, department, working days, deadline). **Import employees…** takes a CSV/Excel export (e.g. from the HR system): headers `full_name`/`name`, optional `email`, `department`, `designation`, `status`; shows a preview before saving; matches by email then name and keeps old spellings as aliases. Click a person for hours, averages, completion, categories, daily trend, recent entries, comparison with the previous period, data-quality and anomaly alerts. |
| **Timesheets** | Every entry, filterable by date, person, costing code, completion and text. |
| **Analytics** | Period KPIs, hours by costing code and a weekly costing-code heatmap, repeated activities, unusual hours, missing timesheets, data quality. |
| **Reports** | Daily management report on screen and as **Excel, CSV, PDF**. Saved automatically every day. |
| **Imports** | Gmail status, manual upload, every received file with its status and issues, background job log. |
| **Settings** | Sync/backup/report schedules, holidays, **Backup Now / Restore**, costing codes, users & roles, access log. |

Alerts are always factual ("recorded 13.5 hours; recent average 8.1"). The app never
labels anyone as productive or unproductive and has no "productivity score" —
timesheets are evidence, not the whole picture of performance.

### How a timesheet is read

The parser finds the table by its **headers** (Costing Code, Notes, File Type,
Completed?, Features, Burden Hours — and common variants), not by cell positions, so
moved columns, extra rows or a shifted table still work. "Name" and "Date" are found by
their labels. A `/` means "not applicable". The "Total Burden Time" row is checked
against the sum of the rows.

Work is grouped by **your own costing codes**, using the hours recorded on each row.
The code list and descriptions are read automatically from the **COSTING CODE** sheet inside
the timesheets; codes used on a row but missing from that list are described from their latest
note (marked "from notes") until someone adds a description in Settings → Costing codes.
Rows with 0 hours (standing items listed but not worked that day) are kept but not counted as tasks.

### Duplicates and corrections

* The same Gmail message is never processed twice.
* An identical file (same SHA-256) is recorded as *duplicate* and not imported.
* A **different** file for the same employee and date replaces the earlier one
  (treated as a corrected timesheet; the older one is kept as *replaced*).

## Data location

Everything local lives under `TIMESHEET_HOME` (default: this folder):

```text
D:\EmployeeTimesheet\
├── data\timesheets.db     the database (single source of truth)
├── backups\               automatic + manual backups
├── reports\YYYY\MM\       daily reports (xlsx, csv, pdf)
├── imports\YYYY\MM\       every received Excel file, as evidence
├── logs\                  app.log
└── secrets\               Gmail OAuth files
```

Each folder can be overridden individually (`TIMESHEET_BACKUP_DIR=E:\Backups`, …). To
move data: stop the app, move the folder, update `.env`, start the app.

**Copy the backups folder off the desktop regularly** (external drive, OneDrive, NAS). A
backup on the same disk does not survive a disk failure.

## Security summary

* Remote access only through **Tailscale** (private network, HTTPS, no router port forwarding, nothing public).
* App login required everywhere; passwords hashed with scrypt; HttpOnly + SameSite=Strict session cookies (Secure over HTTPS); sessions expire.
* Sign-in throttling (5 failures / 15 min per IP); CSRF protection; strict security headers.
* First administrator can only be created from the desktop itself.
* Roles: **admin**, **manager**, **viewer**.
* The database is never exposed — only the web app port. Gmail access is **read-only**; tokens stay in `secrets\`.
* Sign-ins and every non-local request are recorded in Settings → Access log.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## GitHub

The repository contains code, templates, docs and tests only. `.gitignore` excludes
`data/`, `backups/`, `reports/`, `imports/`, `logs/`, `secrets/`, `.env`, all `.db`,
`.xlsx`, `.csv`, `.pdf` files and any credential/token JSON. Check `git status` before
every commit anyway.

## Development

```bat
.venv\Scripts\python.exe -m pytest -q
```

Project layout:

```text
backend/  api/ auth/ database/ models/ excel/ gmail/ analytics/ reports/ services/  main.py config.py
frontend/ index.html styles.css src/app.js services/api.js components/ pages/   (plain JS, no build step)
scripts/  create_admin.py gmail_auth.* install_startup.ps1 setup_tailscale.ps1 seed_demo.py ...
tests/    parser, importer, Gmail sync (simulated), KPIs, API, auth, backup/restore
docs/     architecture, remote access, Gmail setup, operations, phase checkpoints
```

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — design, data model, security, remote-access decision
* [docs/REMOTE_ACCESS.md](docs/REMOTE_ACCESS.md) — Tailscale setup
* [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md) — connecting Gmail
* [docs/OPERATIONS.md](docs/OPERATIONS.md) — startup, backups, restore, troubleshooting, offline behaviour
* [docs/CHECKPOINTS.md](docs/CHECKPOINTS.md) — what each development phase delivered and how it was tested
* [docs/ACCEPTANCE_TESTS.md](docs/ACCEPTANCE_TESTS.md) — the 14 acceptance tests and their status
