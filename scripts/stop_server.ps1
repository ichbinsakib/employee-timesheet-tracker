# Stops the Timesheet Tracker server listening on TIMESHEET_PORT.
. "$PSScriptRoot\_common.ps1"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    # Pause the 5-minute watchdog, otherwise it would start the app again.
    if ($task.State -eq "Running") { Stop-ScheduledTask -TaskName $TaskName }
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Host "Automatic start paused. Run scripts\resume_startup.bat to turn it back on."
}
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) { Write-Host "Nothing is listening on port $Port."; exit 0 }
foreach ($procId in ($conns.OwningProcess | Sort-Object -Unique)) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -match "^pythonw?$") {
        Stop-Process -Id $procId -Force -Confirm:$false
        Write-Host "Stopped Timesheet Tracker (process $procId)."
    } elseif ($p) {
        Write-Host "Port $Port is used by '$($p.ProcessName)' (process $procId), not the Timesheet Tracker. Not stopping it."
    }
}
