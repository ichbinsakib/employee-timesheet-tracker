# Remote access with Tailscale

## Decision

| | Tailscale (chosen) | Cloudflare Tunnel |
|---|---|---|
| Who can reach the app | Only devices signed in to **your** Tailscale account | Anyone on the internet who has the URL (then Cloudflare Access / app login) |
| Public exposure | None — there is no public URL | A public hostname exists |
| Needs a domain | No (`*.ts.net` name is provided) | Yes, a domain on Cloudflare |
| Client install on remote device | Yes (Tailscale app; Windows, Mac, iOS, Android) | No, any browser |
| HTTPS | Yes (Tailscale Serve, automatic certificates) | Yes |
| Router port forwarding | None | None |

The app is for you and internal management, and holds employee information. A private
network with **no public entry point** is the smaller attack surface, so **Tailscale** is
the chosen design (you confirmed Tailscale is fine). The app still requires its own
login on top of Tailscale.

If you later need access from computers where you cannot install anything, Cloudflare
Tunnel + Cloudflare Access can be added in front of the same `http://127.0.0.1:8000`
without changing the app.

## How it fits together

```text
Laptop / phone (Tailscale app, your account)
        │  WireGuard-encrypted tunnel, no open router ports
        ▼
Desktop: Tailscale service ── "tailscale serve" (HTTPS, valid certificate)
        │  http://127.0.0.1:8000
        ▼
Timesheet Tracker (FastAPI) ── SQLite on the desktop
```

Only the web app is published. The database file is never reachable over the network.

## Setup (about 10 minutes, once)

1. **Desktop**: install Tailscale from https://tailscale.com/download/windows and sign in
   (a free personal account is enough).
2. In the Tailscale admin console, **DNS** page (https://login.tailscale.com/admin/dns):
   enable **MagicDNS** and **HTTPS Certificates**.
3. On the desktop, in the project folder:

   ```bat
   powershell -ExecutionPolicy Bypass -File scripts\setup_tailscale.ps1
   ```

   It prints your address, e.g. `https://desktop-abc.tail1234.ts.net`. The setting is
   remembered and survives reboots (Tailscale runs as a Windows service).
4. **Remote device**: install Tailscale, sign in with the **same account**, open the
   address, sign in to the Timesheet Tracker.

To turn remote access off: `scripts\setup_tailscale.ps1 -Off`.

## Hardening options

* With Tailscale Serve in place you can set `TIMESHEET_HOST=127.0.0.1` in `.env`, so the
  app is reachable only through Tailscale and from the desktop itself (no plain-HTTP LAN
  access at all). Restart the app afterwards.
* In the Tailscale admin console you can restrict which of your devices may reach the
  desktop (Access controls), and enable device approval.
* Settings → **Access log** shows every sign-in and every request that did not come from
  the desktop, with the Tailscale IP (100.x.y.z) of the device.

## LAN access without Tailscale (optional)

With `TIMESHEET_HOST=0.0.0.0` (the default), other PCs on the same office network can use
`http://DESKTOP-IP:8000`. Windows Firewall blocks this until you run, as Administrator:

```bat
powershell -ExecutionPolicy Bypass -File scripts\allow_lan_firewall.ps1
```

The rule only applies on **Private** networks and only to the local subnet. LAN access is
plain HTTP; prefer the Tailscale address even inside the office.

**Never** forward port 8000 on your router.

## When the desktop is off

The remote address stops working, because the desktop *is* the server. There is no
cloud copy. See [OPERATIONS.md](OPERATIONS.md).
