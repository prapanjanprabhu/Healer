# Healer V1 release

## Version

`VERSION` at the repo root is the single source of truth (`1.0.0` for this
release). The Go Agent's reported version is injected from it at build
time (`make release-agent`, `internal/version.Version` — a `var`, not a
`const`, specifically so `-ldflags -X` can override it; the un-injected
default `0.5.0-dev` only ever appears in a manual `go build` during
development).

## What's versioned, and what isn't (V1 scope)

- **Agent binaries**: versioned and checksummed. `make release-agent`
  cross-compiles `healer-agent-windows-amd64.exe` and
  `healer-agent-linux-amd64` with the real version injected, and writes a
  `.sha256` file next to each — genuinely built and verified while writing
  this doc (see the checksum output in `docs/dashboard.md`'s sibling
  commit, or just re-run `make release-agent` yourself). Real code signing
  (Windows Authenticode, a GPG-signed release) needs a certificate/private
  key this project doesn't have; the checksum is what an operator
  downloading a release verifies against instead — documented as the
  honest V1 scope, not silently skipped.
- **Control Plane / dashboard / worker / Gateway Manager**: built from
  source via Docker Compose (`deploy/docker-compose.yml`), not published
  as pre-built version-tagged images in V1. "Versioned release" for these
  four means: tag the *source* (a git tag matching `VERSION`), and
  `docker compose build` produces that version's images locally. A
  registry-published, pre-built image per version is a reasonable next
  step but wasn't required for V1 and isn't pretended to exist here.
- **Postgres/Redis**: already pinned (`postgres:16-alpine`,
  `redis:7-alpine`) — unrelated to Healer's own version.

## Explicit confirmation: none of the excluded technologies are present

Grepped for, not just asserted:

- **Prometheus / Grafana / Loki**: zero references anywhere in
  `services/`, `agent/`, `apps/`, `deploy/`, or `docs/` other than the
  repeated statements that V1 does *not* use them
  (`docs/architecture.md` §7, `docs/metrics-and-logs.md`, README). Metrics
  are the Agent's own heartbeat -> `MetricsSnapshot` rows (Phase 5/12);
  logs are local files + the Phase 12 bounded-read/live-tail feature — no
  external metrics/log aggregation system exists or is referenced.
- **ACME**: zero references to the actual protocol. (A grep for "acme"
  does hit real files — `services/gateway-manager/tests/test_nginx_manager.py`
  and others — but every one is the placeholder test app slug "acme"/
  "acme-erp" (the "Acme Corp" naming convention), plus this project's own
  "(no ACME)" confirmation text in `apps/dashboard/.../certificates/page.tsx`.
  Worth knowing before a future re-check assumes a hit means the exclusion
  broke.) Certificates are existing CRT/KEY filesystem paths only
  (`docs/security-boundaries.md` §5) — no ACME client dependency, no Let's
  Encrypt integration, nothing that requests or renews a certificate
  automatically.
- **Kubernetes**: zero references. No `kubectl`, no manifest, no operator/
  controller pattern, no `client-go` dependency anywhere in `agent/`'s
  `go.mod` or `services/*/requirements.txt`.
- **Buildpacks**: zero references. The Linux adapter builds from a
  Dockerfile the administrator supplies (`docs/linux-docker-adapter.md`)
  or pulls an explicit image reference — never a buildpack-style
  auto-detected build.
- **Arbitrary remote shell**: structurally impossible, not just policy.
  Every Agent command is one of a closed, ten-member enum
  (`AgentCommandType` on both the Control Plane and Go Agent sides,
  `docs/agent-protocol.md`) — there is no "run this shell string" command
  type in the protocol, and the Go dispatcher panics if code ever tries to
  register a handler for an unrecognized type
  (`agent/internal/dispatcher/dispatcher.go`).

## Acceptance checklist

Exercised live, for real, at least once during this project (see each
phase's own docs for the specific verification session) — re-run this
list against a clean install before calling a release final:

- [ ] A clean Healer Linux server (Control Plane, dashboard, worker,
      Gateway Manager via `docker compose up -d`) comes up healthy
      (`GET /health`, a real login).
- [ ] A Windows server enrolls (`docs/windows-agent-install.md`) and shows
      **online**.
- [ ] A Linux server enrolls (`docs/linux-agent-install.md`, real Docker
      daemon reachable) and shows **online**.
- [ ] A Windows Django/Waitress application deploys, scales, health-checks,
      routes through the gateway, blue-green-releases, and rolls back
      (Phases 7-11).
- [ ] A Linux Docker application deploys, scales, health-checks, routes
      through the gateway, blue-green-releases, and rolls back
      (Phase 13).
- [ ] Killing one running instance directly (not through the dashboard)
      triggers self-healing recovery without dropping the other replicas'
      traffic (Phase 10).
- [ ] Metrics (CPU/RAM/disk) and a live log tail render on the dashboard
      for a real instance, with a deliberately-logged secret-looking value
      redacted (Phase 12).
- [ ] Every dashboard page an Administrator needs is reachable without a
      raw API call: Overview, Servers, Applications (create + detail),
      Deployments (list + detail), Health, Certificates, Audit Log, Users,
      Settings (Phase 14).
- [ ] A Viewer/Operator cannot see or trigger an action their role doesn't
      grant, both in the UI (hidden) and at the API (403).
- [ ] `make backup && make restore FILE=...` round-trips real data
      (Phase 15 — genuinely re-run this, don't just trust the doc).
- [ ] A real concurrent load test
      (`scripts/load_test_erp.sh`) against the expected peak succeeds with
      instances staying healthy throughout.
- [ ] Restarting the Control Plane mid-deployment reconciles the stuck
      deployment/instance to a clean failed state rather than leaving it
      stuck (Phase 15).
- [ ] `POST /servers/{id}/agent/revoke` genuinely disconnects a live Agent
      and its old credential can no longer reconnect (Phase 15).
- [ ] This document's "explicit confirmation" section still holds — re-grep
      before signing off on a release, don't just trust that it hasn't
      changed.
