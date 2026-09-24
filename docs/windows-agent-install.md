# Installing the Agent on a Windows server

This is the exact sequence used to enroll every real Windows server verified
throughout this project (see the live-verification notes in
`docs/app-deployment.md`, `docs/self-healing.md`, `docs/blue-green-deployment.md`).

## Prerequisites

- Windows 10/11 or Windows Server, Administrator access.
- Outbound network access to the Control Plane's WebSocket port (see
  `docs/firewall-and-network.md` — no inbound rule is ever needed).
- A Python interpreter already installed on the server for whichever
  Django/Waitress applications will be deployed here (the Agent doesn't
  install Python itself — `healer.yaml`'s `windows.python_executable`
  points at an existing one).

## 1. Get the binary and its checksum

Download `healer-agent-windows-amd64.exe` and
`healer-agent-windows-amd64.exe.sha256` for the release you're installing
(built by `make release-agent` — see `docs/release.md`). Verify it before
running anything:

```powershell
Get-FileHash healer-agent-windows-amd64.exe -Algorithm SHA256
# compare against the .sha256 file's value
```

Place the binary somewhere permanent — it keeps running as the installed
service's executable, so don't delete or move it after installing.

## 2. Register the server and get an enrollment token

In the dashboard: **Servers -> Add Server**, OS = Windows. Then open that
server's detail page and issue an enrollment token (Administrator role
required) — it's single-use and expires (60 minutes by default).

## 3. Enroll

From an elevated PowerShell prompt, in the directory holding the binary:

```powershell
.\healer-agent.exe enroll --control-plane https://<your-control-plane-host>:8000 --token <the-token-you-just-issued>
```

This saves a config file and a long-lived connection credential under the
Agent's data directory (`%ProgramData%\Healer` by default — see
`agent/internal/config`). The raw enrollment token is single-use; the
credential this step receives is what the Agent reconnects with from then
on.

## 4. Install and start the Windows Service

```powershell
.\healer-agent.exe service install
.\healer-agent.exe service start
```

Confirm it's running:

```powershell
Get-Service HealerAgent
```

...and confirm it shows as **online** on the server's dashboard page —
that's the real signal the enrollment/service install worked end to end
(the Agent completed its WebSocket handshake and sent its first
heartbeat).

## Verifying it's really working

`healer-agent.exe -version` prints the build version. Application
instances this Agent will manage run as their own separate Windows
Services (named `Healer-<app-slug>-<port>`, installed under the
low-privilege `NT AUTHORITY\LocalService` account — see
`docs/app-deployment.md`) — the Agent itself typically runs as
LocalSystem so it can install/manage those.

## Uninstalling

```powershell
.\healer-agent.exe service stop
.\healer-agent.exe service uninstall
```

This removes the `HealerAgent` Windows Service only. It does **not**:
- Remove any application instance services the Agent installed
  (`Healer-<app-slug>-<port>`) — stop/remove those first via the dashboard
  (scale to 0, or delete the application) so Healer's own bookkeeping
  stays consistent; removing them out from under a live Instance row
  leaves the Control Plane thinking they still exist.
- Delete the Agent's data directory (journal, credential, logs) — remove
  `%ProgramData%\Healer` by hand for a truly clean slate.
- Revoke the server's enrollment on the Control Plane side — do that from
  the dashboard (`POST /servers/{id}/agent/revoke`, Administrator role) if
  you're decommissioning the server for good, so its credential can never
  be used to reconnect.

## Re-installing / upgrading in place

Stop the service, replace the `.exe` with the new version's binary (same
path), start the service again — no re-enrollment needed, the saved
credential and config are untouched by a binary swap. See
`docs/upgrade-and-rollback.md`.
