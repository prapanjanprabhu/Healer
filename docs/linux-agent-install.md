# Installing the Agent on a Linux server

## Prerequisites

- A real Docker daemon reachable at `/var/run/docker.sock` (rootful or the
  common rootless setups that expose the socket at that path) — required
  for the `linux-docker` adapter (`docs/linux-docker-adapter.md`). Confirm
  with `docker version` before enrolling.
- systemd (the provided unit file assumes it).
- Outbound network access to the Control Plane's WebSocket port — see
  `docs/firewall-and-network.md`.

## 1. Get the binary and its checksum

```bash
sha256sum -c healer-agent-linux-amd64.sha256
```

## 2. Register the server and get an enrollment token

Dashboard: **Servers -> Add Server**, OS = Linux, then issue an enrollment
token from that server's detail page (Administrator role).

## 3. Enroll

```bash
sudo ./healer-agent enroll --control-plane https://<your-control-plane-host>:8000 --token <the-token>
```

Saves the config and long-lived credential under `/var/lib/healer` by
default.

## 4. Install as a systemd service

```bash
sudo ./agent/systemd/install.sh ./healer-agent
```

This is a real, runnable script (`agent/systemd/install.sh`) — not just
documentation. It copies the binary to `/usr/local/bin/healer-agent`,
installs `agent/systemd/healer-agent.service`, and runs
`systemctl enable --now healer-agent`. The unit restarts the Agent
automatically on failure (`Restart=on-failure`).

```bash
systemctl status healer-agent
journalctl -u healer-agent -f
```

Confirm the server shows **online** on its dashboard page.

## Uninstalling

```bash
sudo ./agent/systemd/uninstall.sh
```

Stops and removes the systemd unit. It deliberately does **not** delete
`/var/lib/healer` (journal, credential, local logs) — remove that by hand
for a clean slate. As on Windows, this doesn't touch application
containers the Agent was managing or revoke the server's enrollment on the
Control Plane side — do those first/separately (scale the application to
0 or delete it; `POST /servers/{id}/agent/revoke` to revoke the
credential).

## Upgrading in place

```bash
sudo systemctl stop healer-agent
sudo install -Dm755 ./healer-agent-new /usr/local/bin/healer-agent
sudo systemctl start healer-agent
```

No re-enrollment needed. See `docs/upgrade-and-rollback.md`.
