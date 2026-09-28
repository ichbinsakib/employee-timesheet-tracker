@echo off
rem Turns the Timesheet Tracker automatic start back on (after stop.bat) and starts it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0resume_startup.ps1"
pause
