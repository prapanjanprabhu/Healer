# Healer Agent

Go binary that runs on each managed Windows or Linux server and connects
outbound to the Control Plane over a secure WebSocket (`wss://`). See
[`docs/architecture.md`](../docs/architecture.md) and
[`docs/security-boundaries.md`](../docs/security-boundaries.md).

## Build

```bash
go build -o bin/healer-agent ./cmd/healer-agent
```

Cross-compile for a target platform, e.g. Windows from any host:

```bash
GOOS=windows GOARCH=amd64 go build -o bin/healer-agent.exe ./cmd/healer-agent
```

## Run

```bash
./bin/healer-agent -version
```

## Phase 1 scope

- `cmd/healer-agent` — entrypoint, prints version, validates config.
- `internal/config` — configuration shape loaded from environment variables.
- `internal/transport` — outbound WebSocket client contract stub (not yet
  implemented).
- `internal/version` — build version constant.

Connecting to the Control Plane and running the Windows (Waitress/Windows
Service) or Linux (Docker) V1 adapters are implemented alongside deployment
behavior in a later phase.
