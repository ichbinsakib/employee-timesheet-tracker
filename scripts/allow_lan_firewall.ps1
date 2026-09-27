<#
OPTIONAL. Lets other computers on your office/home network open http://THIS-PC-IP:8000.
Only needed for LAN access without Tailscale. Run as Administrator.
The rule is limited to the Private network profile (never Public networks) and to the local subnet.
Remove it with:  Remove-NetFirewallRule -DisplayName "Timesheet Tracker (LAN)"
#>
. "$PSScriptRoot\_common.ps1"
$name = "Timesheet Tracker (LAN)"
Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow `
    -Profile Private -RemoteAddress LocalSubnet | Out-Null
Write-Host "Allowed TCP $Port from the local subnet on Private networks."
Write-Host "Check your network is set to Private: Settings > Network & internet > (your network) > Private network."
