# Running the desktop server

## Start, stop, start with Windows

| Task | How |
|---|---|
| Start (visible window) | double-click `start.bat` |
| Stop | close that window, or double-click `stop.bat` (also pauses the automatic start) |
| Resume automatic start after `stop.bat` | double-click `scriptsesume_startup.bat` |
| Start automatically, hidden, at your Windows sign-in | `powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1` |
| …at boot, before anyone signs in (as Administrator) | `… scripts\install_startup.ps1 -AtBoot` |
| Remove automatic start | `… scripts\uninstall_startup.ps1` |

The startup task runs `pythonw.exe run_server.py` from the project folder at sign-in
(or boot) and, as a watchdog, **every 5 minutes**: if the app has stopped for any reason,
it is started again within 5 minutes (tested: stopped at 14:42:48, back at 14:43:48).
Only one instance can run — if port 8000 is already in use, the extra start exits at once.
`stop.bat` disables the task so the watchdog does not bring the app straight back;
`scriptsesume_startup.bat` turns it back on.

One process does everything: the web app, the Gmail check, backups and daily reports.
**Closing Chrome does not stop anything.**

For a true 24/7 server, also set Windows **Power & sleep → Sleep: Never** (when plugged
in); a sleeping PC is an offline server. `-AtBoot` keeps the app running after a
Windows Update restart even if nobody signs in.

## If the desktop is off

* The web app is unavailable locally and remotely.
* Gmail is not checked; emails simply wait in Gmail.
* On the next start the app automatically:
  1. checks Gmail for the last `GMAIL_LOOKBACK_DAYS` (14) days and imports anything new,
  2. takes a backup if the last one is older than the backup interval,
  3. writes any daily report from the last 3 days that was missed.

If the desktop is off for longer than the look-back period, raise
**Settings → Look back (days)** before starting, or upload the files manually on **Imports**.

## Backups

* Automatic every `BACKUP_INTERVAL_HOURS` (24), keeping the newest `BACKUP_RETENTION` (30).
* **Backup Now** on Settings → Backups.
* Uses SQLite's online backup API: consistent while the app runs.
* Location: `TIMESHEET_BACKUP_DIR` (default `<TIMESHEET_HOME>\backups`). Point it at
  another drive, or sync the folder to OneDrive/NAS. **A backup on the same disk does not
  protect against disk failure.**
* The `imports\` folder holds every original Excel file; include it in your off-PC copy.

## Restore

Settings → Backups → **Restore…** (administrators only):

1. The backup is checked first (SQLite header, integrity check, required tables) and
   its contents are summarised.
2. You must type `RESTORE` to confirm.
3. A `…_pre-restore.db` safety copy of the current database is taken automatically.
4. The backup is copied into the live database; you sign in again.

A backup file from elsewhere can be added with **Upload a backup…** and then restored
the same way. To undo a restore, restore the `pre-restore` copy.

## Users and passwords

* Settings → Users (admin): add users as **admin**, **manager** (import, sync, back up,
  edit employees) or **viewer** (read-only).
* Forgotten password (on the desktop):
  `.venv\Scripts\python.exe scripts\create_admin.py --username admin --reset`

## Logs

* `logs\app.log` (rotated at 5 MB, 5 files) — imports, sync, backups, errors.
* Imports → Background activity — every Gmail check, backup and report with its result.
* Settings → Access log — sign-ins and all remote requests (kept 180 days).

## Updating the app

```bat
stop.bat
git pull
.venv\Scripts\python.exe -m pip install -r requirements.txt
start.bat   (or wait for the startup task to restart it)
```

New tables are created automatically at start. Your data folder is never touched by Git.

## Moving to PostgreSQL later

Set `DATABASE_URL=postgresql+psycopg://…` in `.env` (and `pip install psycopg[binary]`).
The models use only portable types. Built-in Backup/Restore are SQLite-only; use
`pg_dump` for PostgreSQL. Copying existing data across needs a one-off migration script.

## Troubleshooting

| Symptom | Check |
|---|---|
| http://localhost:8000 does not load | Is it running? `stop.bat` then `start.bat` and read the window. Otherwise `logs\app.log`, `logs\server-console.log`. |
| Remote address does not load | Desktop on and awake? Tailscale connected on both devices? `tailscale serve status` on the desktop. |
| Can sign in locally but not remotely | Same account? Throttled after 5 failed attempts (wait 15 min). |
| Timesheet shows "Failed" | Imports → click it for the reason (no table found, no date, .xls file…). Fix the file and upload it, or ask for a new email. |
| A person appears twice | Edit the right employee and add the other spelling to "Other spellings"; remove the wrong import (admin) and re-upload. |
