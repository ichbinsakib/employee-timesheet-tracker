# Acceptance tests

Status as delivered (2026-09-27). "Automated" means covered by `tests/test_acceptance.py`
and the other test files (29 tests, all passing). "Manual" items need your Gmail account,
your Tailscale account or a real reboot, which could not be done during development.
They are **not yet verified**.

| # | Test | Status | How it was checked / how to check |
|---|---|---|---|
| 1 | Employee emails Excel timesheet | Automated (simulated Gmail) · **Manual: pending** | Send a timesheet (e.g. the real "Employee Production Sheet") to the connected mailbox. |
| 2 | Desktop automatically detects it | Automated (simulated) · **Manual: pending** | Within 15 min, or press Sync Gmail Now; Imports shows the file. |
| 3 | Excel is downloaded | Automated | File saved under `imports\YYYY\MM\` (asserted). |
| 4 | Data is parsed | Automated | Real layout replica: name, date, P4627, 16 activity lines, 10.4 h. Shifted/re-ordered layouts also tested. |
| 5 | Data is validated | Automated | Bad hours, Yes/No, features, total mismatch, short notes, missing name/date, .xls. |
| 6 | Data is stored on the desktop | Automated · Verified live | SQLite file in `TIMESHEET_HOME\data`. |
| 7 | KPI calculations performed | Automated | Hours, averages, completion, costing codes, features, missing, anomalies, baselines. |
| 8 | Dashboard updates | Automated · Verified in browser (demo data) | Dashboard, employee detail, timesheets, analytics, reports, imports, settings pages rendered with 154 demo timesheets. |
| 9 | Daily report generated | Automated · Verified live | xlsx/csv/pdf written on schedule and on startup catch-up. |
| 10 | Duplicate email not imported twice | Automated | Same message skipped; identical file in another email recorded as duplicate. |
| 11 | Access locally | Automated · Verified in browser | http://localhost:8765 (demo instance). Use http://localhost:8000 for the real one. |
| 12 | Access from another network | Automated (simulated Tailscale client) · **Manual: pending** | After docs/REMOTE_ACCESS.md: open the `https://…ts.net` address on a phone on mobile data. |
| 13 | Both show the same database | Automated (simulated) · **Manual: pending** | Compare the dashboard on both devices; check Settings → Access log shows the remote device. |
| 14 | Desktop restarts, app resumes | Verified: process restart with hidden `pythonw` (as the startup task runs it); catch-up ran Gmail check, backup, missed reports; second start did not repeat them · **Manual: pending** real reboot with the scheduled task installed | Install `scripts\install_startup.ps1`, reboot, open http://localhost:8000; Imports → Background activity shows "startup" runs. |

## Manual acceptance checklist (after setup)

1. `start.bat` → http://localhost:8000 → create administrator.
2. Connect Gmail (docs/GMAIL_SETUP.md). Imports shows **Connected**.
3. Ask one employee to email today's timesheet (or email one yourself).
4. Press **Sync Gmail Now** → Imports shows it *Imported*; Dashboard shows the hours.
5. Press **Sync Gmail Now** again → "0 new"; no second row in Timesheets.
6. Reports → Excel / CSV / PDF open correctly.
7. Settings → Backups → **Backup Now** → file appears in the backups folder.
8. Tailscale (docs/REMOTE_ACCESS.md) → open the ts.net address on a phone using mobile
   data → sign in → same numbers as on the desktop.
9. `scripts\install_startup.ps1` → restart Windows → without opening anything, visit the
   app from the phone.
