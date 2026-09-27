@echo off
rem Stops the Timesheet Tracker, whether it was started by start.bat or by the startup task.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_server.ps1"
