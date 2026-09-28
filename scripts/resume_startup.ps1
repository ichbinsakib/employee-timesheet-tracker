# Turns the automatic start back on after stop.bat, and starts the app now.
. "$PSScriptRoot\_common.ps1"
if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Write-Host "No startup task installed. Run scripts\install_startup.ps1 first."; exit 1
}
Enable-ScheduledTask -TaskName $TaskName | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Automatic start resumed. The app is starting on http://localhost:$Port"
