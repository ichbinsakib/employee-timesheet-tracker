<#
Runs the Timesheet Tracker automatically, hidden, whenever Windows starts.

    powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1            # at your sign-in (no admin needed)
    powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1 -AtBoot    # at boot, before anyone signs in (run as Administrator)

The task restarts the app if it stops unexpectedly. Remove with scripts\uninstall_startup.ps1.
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
