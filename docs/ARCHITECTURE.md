# Architecture

## Principles

* **One source of truth**: a single SQLite file on the desktop. Every browser, local or
  remote, talks to the same FastAPI process, which is the only thing that opens the
  database.
* **The browser never touches the database**: all reads and writes go through the
  authenticated JSON API.
* **Nothing in the cloud** except Gmail (source of timesheets) and Tailscale (encrypted
  connectivity). No SaaS database, no Google Sheets, no automation platforms.
* **Descriptive, not judgemental analytics.**

## Components (one Python process)

```text
run_server.py ── uvicorn ── backend.main:app (FastAPI)
                              ├── security middleware (CSRF, headers, remote access log)
                              ├── /api/*  routers: auth, dashboard, employees, timesheets,
                              │                    analytics, reports, imports, settings
                              ├── /static/*  frontend (plain ES modules, no build step)
                              └── APScheduler (background thread)
                                    ├── gmail_sync   every N minutes
                                    ├── backup       every N hours
                                    ├── daily_report daily at HH:MM
                                    ├── cleanup      03:30 (expired sessions, old access log)
                                    └── catch_up     10 s after start (missed work)
```

| Module | Responsibility |
|---|---|
| `backend/config.py` | Settings from `.env`; data folder layout |
| `backend/models` | SQLAlchemy models (portable types → PostgreSQL-ready) |
| `backend/database` | Engine/session holder (swappable after restore), table creation, seed data |
| `backend/excel/parser.py` | Header-based table detection, label-based name/date, total row |
| `backend/excel/validator.py` | Type conversion + data-quality issues per row/sheet |
| `backend/services/importer.py` | One pipeline for Gmail and uploads: dedupe, identify employee, date fallbacks, resubmission, store, classify |
| `backend/services/classifier.py` | Notes → activity lines → keyword rules → category |
| `backend/gmail` | Read-only Gmail client, sync (lookback window, processed-message table) |
| `backend/analytics/kpi.py` | KPIs, series, baselines, anomalies, missing days, data quality |
| `backend/analytics/alerts.py` | Factual management alerts |
| `backend/reports/daily.py` | Daily report → xlsx / csv / pdf |
| `backend/services/backup.py` | Online backup, retention, validated restore with safety copy |
| `backend/auth` | scrypt hashing, server-side sessions, roles, throttling, client classification |

## Data model

```text
employees ─┬─< submissions >── gmail_messages (by gmail_message_id)
           │        │
           │        ├─< data_quality_issues
           │        └─< timesheet_entries ─< entry_activities >── work_categories
           │                                                   ▲
           └─< timesheet_entries                classification_rules
users ─< auth_sessions        access_log   app_settings   job_runs   generated_reports
```

* **employees** — name, aliases, email, department, job title, expected daily/weekly hours,
  working days, submission deadline, tracking start, active, auto_created.
* **submissions** ("Gmail Submissions") — one per received sheet: source (gmail/upload),
  Gmail message id, sender, filename, SHA-256, stored path, email/import timestamps,
  work date, import status (`imported`, `imported_with_warnings`, `failed`, `duplicate`,
  `superseded`), duplicate status (`unique`, `duplicate_file`, `resubmission`), totals.
* **timesheet_entries** — work date, costing code, heading, notes, file type,
  completed (true/false/**null = not recorded**), feature count, burden hours,
  original Excel row, primary category.
* **entry_activities** — each note line, its category, matched keyword and estimated hours.
* **work_categories**, **classification_rules** (keyword, category, priority, active).
* **gmail_messages** — every message examined, so nothing is processed twice.

## Import pipeline

```text
bytes ─▶ extension check ─▶ SHA-256 already imported? ─yes─▶ record "duplicate"
                               │no
                               ▼
         parse workbook (each visible sheet with a recognisable header row)
                               ▼
  employee: sheet name ▶ aliases ▶ honorific-insensitive ▶ sender email ▶ auto-create
  date:     sheet label ▶ file name ▶ email date (each fallback raises a warning)
                               ▼
     validate rows (hours 0–24, Yes/No, whole-number features, notes present,
     stated total = sum, future/old date, non-working day)
                               ▼
  same employee + date already imported? ─▶ older → "superseded", rows replaced
                               ▼
     store entries ─▶ split notes into lines ─▶ classify ─▶ allocate hours
```

## KPIs (all computed on demand from stored rows)

Total hours · average daily hours (per submitted day) · tasks (rows) and activity lines ·
completed / incomplete / not recorded · completion rate (of recorded Yes/No only) ·
average hours per task · category distribution (estimated hours) · administrative /
communication / coordination % · feature workload and hours per feature · repeated
activities (same normalised wording on ≥ 2 days) · daily and weekly series · weekly
category share · missing timesheets (expected working days, holidays excluded, today only
after the deadline) · data-quality issues · previous-period baseline and comparison ·
anomalies (daily hours ≥ max(2σ, 2 h) from the previous 20 submitted days, or ≥ threshold;
category shifts ≥ 10 points).

## Security

| Threat | Control |
|---|---|
| Internet exposure | No port forwarding. Remote access only via Tailscale (device must be in your tailnet). Only the web port is served; the DB is a local file. |
| Eavesdropping | Tailscale (WireGuard) + HTTPS via Tailscale Serve. HSTS when served over HTTPS. |
| Password theft from DB | scrypt (n=2¹⁴, r=8, p=1) with per-user salt. |
| Session theft | 256-bit random token, HttpOnly, SameSite=Strict, Secure on HTTPS; only SHA-256 of token stored; expiry (12 h); logout and password change revoke sessions. |
| CSRF | SameSite=Strict + mandatory `X-Requested-With` header + Origin/Host check on every state-changing request. |
| XSS / clickjacking | All dynamic text HTML-escaped; CSP `script-src 'self'`; `frame-ancestors 'none'`; X-Frame-Options DENY; nosniff. |
| Brute force | 5 failures per IP per 15 min → HTTP 429. |
| Takeover of a fresh install | First admin can only be created from the desktop itself (loopback, not proxied). |
| Spoofed forwarding headers | `X-Forwarded-*` trusted only when the direct peer is 127.0.0.1 (Tailscale Serve). |
| Path traversal | Backup names validated against a strict pattern; file downloads confined to their folders. |
| Gmail misuse | `gmail.readonly` scope only; token file only on the desktop. |
| Secrets in Git | `.gitignore` covers data, backups, reports, imports, logs, secrets, `.env`, db/xlsx/csv/pdf, credential JSON. |
| Accountability | Access log: sign-ins (ok/failed/blocked), restores, every non-local API request. |

## Known limitations

* Category hours are estimates (hours split evenly across note lines).
* `.xls` (Excel 97–2003) is not supported; files are recorded as failed with a clear message.
* Formulas are read from Excel's cached values; a file generated by a program that never
  calculated formulas shows empty cells there (flagged as missing hours).
* One process, one desktop. Two copies of the app pointed at the same database file is not supported.
* Built-in backup/restore works for SQLite only.
