<#
Publishes the app privately on your Tailscale network with HTTPS:

    https://<this-pc>.<your-tailnet>.ts.net   ->   http://127.0.0.1:8000

Only devices signed in to YOUR Tailscale account can reach it. Nothing is
opened on your router and nothing is exposed to the public internet.

Before running: install Tailscale (https://tailscale.com/download/windows), sign in,
and in the admin console enable MagicDNS and HTTPS certificates (DNS page).
#>
param([switch]$Off)
. "$PSScriptRoot\_common.ps1"

$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts) {
    $default = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $default) { $ts = $default } else { Write-Error "Tailscale is not installed. Get it from https://tailscale.com/download/windows"; exit 1 }
} else { $ts = $ts.Source }

if ($Off) { & $ts serve reset; Write-Host "Tailscale Serve turned off."; exit 0 }

$status = & $ts status --json | ConvertFrom-Json
if ($status.BackendState -ne "Running") { Write-Error "Tailscale is not connected. Open Tailscale and sign in first."; exit 1 }

# --bg keeps serving after this window closes and across reboots (Tailscale runs as a Windows service).
& $ts serve --bg $Port
if ($LASTEXITCODE -ne 0) {
    Write-Host "If Tailscale says HTTPS is not enabled: open https://login.tailscale.com/admin/dns, enable MagicDNS and HTTPS Certificates, then run this again."
    exit 1
}
$name = $status.Self.DNSName.TrimEnd(".")
Write-Host ""
Write-Host "Remote address (from any device signed in to your Tailscale account):"
Write-Host "    https://$name"
Write-Host ""
& $ts serve status
