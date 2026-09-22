# Healer Agent

Go binary that runs on each managed Windows or Linux server: it enrolls once
against the Control Plane, then keeps a persistent outbound WebSocket
connection open (reconnecting with backoff whenever it drops), heartbeats,
and executes the closed set of structured commands the Control Plane sends
it. See [`docs/agent-protocol.md`](../docs/agent-protocol.md) for the wire
protocol and [`docs/agent-runtime.md`](../docs/agent-runtime.md) for this
binary's internals, [`docs/security-boundaries.md`](../docs/security-boundaries.md)
for the trust model.

## Build

```bash
go build -o bin/healer-agent ./cmd/healer-agent
```

Cross-compile for a target platform, e.g. Windows from any host:

```bash
GOOS=windows GOARCH=amd64 go build -o bin/healer-agent.exe ./cmd/healer-agent
```

## Use

```bash
healer-agent -version

# One-time: exchange a single-use enrollment token (issued from the
# dashboard's server detail page) for a long-lived connection credential.
healer-agent enroll --control-plane http://localhost:8000 --token <token>

# Run in the foreground (Ctrl+C / SIGTERM/SIGINT for a clean shutdown).
healer-agent run

# Install/start/stop/uninstall as a native OS service (Windows Service via
# the SCM; systemd unit on Linux). Requires an administrator/root shell.
healer-agent service install
healer-agent service start
healer-agent service stop
healer-agent service uninstall
```

On Linux, `agent/systemd/install.sh` and `uninstall.sh` are the standalone
alternative to `healer-agent service install/uninstall` — useful when you're
bootstrapping a server from a downloaded tarball rather than a binary
already in place.

Data (config, credential, local command journal, logs) lives under:

- Windows: `C:\ProgramData\Healer`
- Linux: `/var/lib/healer`

## Phase 5 scope

- `cmd/healer-agent` — CLI: `enroll`, `run`, `service install|start|stop|uninstall`, `-version`.
- `internal/config` — OS-appropriate config load/save.
- `internal/credentials` — local storage of the long-lived connection credential.
- `internal/enroll` — the one-time `POST /agents/enroll` REST call.
- `internal/protocol` — Go types mirroring `protocols/v2`.
- `internal/transport` — the persistent WebSocket client: reconnect with
  exponential backoff + jitter, heartbeat loop, protocol version
  compatibility check, clean shutdown on context cancellation.
- `internal/core` — wires transport + journal + dispatcher into the Agent's
  actual message handling (hello, heartbeat, command lifecycle).
- `internal/journal` — durable, replay-on-restart local record of
  completed command IDs, so a redelivered or re-attempted command is never
  executed twice.
- `internal/dispatcher` — routes a command to its handler; recognizes all
  ten structured command types but only implements `inspect_host` in this
  phase (a safe, read-only command) — the rest are safely rejected as
  "not implemented" rather than silently ignored or run unsafely.
- `internal/metrics` — CPU/RAM/disk collection (gopsutil).
- `internal/logging` — structured (slog) logging; a redaction helper for
  the (never actually logged) credential.
- `internal/service` — Windows Service (`golang.org/x/sys/windows/svc`) and
  Linux systemd (`systemctl`) install/start/stop/uninstall, behind the same
  `RunAsService`/`Install`/`Uninstall`/`Start`/`Stop` API regardless of OS.
- `systemd/` — the standalone unit file + install/uninstall shell scripts.

Application deployment handlers (`deploy_release`, `start_instance`, etc.)
are not implemented yet — that's a later phase, layered on top of this
foundation via `internal/dispatcher.Register`.
