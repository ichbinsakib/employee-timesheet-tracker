@echo off
rem Connect Gmail (run on the desktop; a browser window opens for Google sign-in).
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\gmail_auth.py
pause
