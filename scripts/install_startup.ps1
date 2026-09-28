<#
Runs the Timesheet Tracker automatically, hidden, whenever Windows starts.

    powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1            # at your sign-in (no admin needed)
    powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1 -AtBoot    # at boot, before anyone signs in (run as Administrator)

The task also re-checks every 5 minutes and starts the app again if it has stopped
(a second copy exits at once when the app is already running).
stop.bat pauses this; scripts\resume_startup.bat resumes it. Remove with scripts\uninstall_startup.ps1.
#>
param([switch]$AtBoot)
. "$PSScriptRoot\_common.ps1"

$pythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { Write-Error "Run start.bat once first so the Python environment is created."; exit 1 }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "run_server.py" -WorkingDirectory $ProjectRoot
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$user = "$env:USERDOMAIN\$env:USERNAME"

if ($AtBoot) {
    # S4U: runs without anyone signed in and without storing your password.
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
}
# Watchdog: a second trigger that fires every 5 minutes, indefinitely. Windows' own
# "restart on failure" only covers a task that fails to start, not an app that stops later.
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$trigger = @($trigger, $watchdog)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Employee Timesheet Tracker: web app, Gmail sync, backups and daily reports." -Force | Out-Null
Write-Host "Installed scheduled task '$TaskName' ($(if ($AtBoot) {'at boot'} else {'at sign-in'}))."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Running: http://localhost:$Port"
} else {
    Write-Host "Task started but port $Port is not listening yet. Check logs\app.log and logs\server-console.log."
}
