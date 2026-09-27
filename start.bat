@echo off
rem Starts the Timesheet Tracker (web app + Gmail sync + backups + reports).
rem Keep this window open, or use scripts\install_startup.ps1 to run it hidden at Windows sign-in.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating Python environment...
  python -m venv .venv || (echo Python 3.11+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Installing packages failed. & pause & exit /b 1)
)
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example - edit it to choose where your data is stored.
)
echo Starting... open the address shown below in Chrome. Close this window to stop the app.
".venv\Scripts\python.exe" run_server.py
if errorlevel 1 pause
