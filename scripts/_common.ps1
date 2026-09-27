# Shared helpers for the PowerShell scripts.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TaskName = "Timesheet Tracker"

function Get-EnvValue([string]$Name, [string]$Default) {
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match "^\s*$Name\s*=\s*(.*)\s*$" -and $Matches[1] -ne "") { return $Matches[1].Trim() }
        }
    }
    return $Default
}

$Port = [int]$(if ($env:TIMESHEET_PORT) { $env:TIMESHEET_PORT } else { Get-EnvValue "TIMESHEET_PORT" "8000" })
