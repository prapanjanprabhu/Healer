# Healer

Healer is a self-hosted deployment and application-management platform for
Windows and Linux servers. An administrator uses one web dashboard to register
servers, connect application code, deploy it, control instance counts, route
traffic through one central Nginx gateway, watch health, and roll back bad
releases.

**Healer is the management system. It does not sit inside the normal
application request path.**

## Two paths, kept separate

- **Management path** — Administrator → Dashboard → Control Plane API →
  (PostgreSQL, Redis/Celery worker, Agents over WebSocket, Gateway Manager).
  This is where deploys, health checks, restarts and rollbacks are decided.
- **User-traffic path** — End user → Nginx (one central gateway) → application
  instance (Waitress on Windows, Docker container on Linux). Healer's own
  services are never in this path; if the control plane is offline, already
  deployed applications keep serving traffic unaffected.

See [`docs/architecture.md`](docs/architecture.md) for the full breakdown and
[`docs/security-boundaries.md`](docs/security-boundaries.md) for why the Gateway
Manager and agents are isolated the way they are.

## Repository layout

| Path | What it is |
|---|---|
| `apps/dashboard` | Next.js + TypeScript admin dashboard |
| `services/control-plane` | FastAPI control plane API, PostgreSQL + Alembic |
| `services/worker` | Celery worker (Redis broker/backend) for durable jobs |
| `services/gateway-manager` | Restricted service that owns the central Nginx config |
| `agent` | Go agent (`cmd/healer-agent`) run on each managed server |
| `protocols` | Versioned JSON schemas for control-plane ↔ agent messages |
| `deploy` | Docker Compose stack + Nginx config templates |
| `docs` | Architecture, security boundaries, development guide |

## Fixed technology (V1)

Dashboard: Next.js/React/TypeScript · Control Plane: FastAPI · Persistence:
PostgreSQL + migrations · Job queue: Redis + Celery · Agent: Go (Windows +
Linux) over outbound secure WebSocket · Public gateway: one central Nginx
behind a restricted Gateway Manager · Windows adapter: Django/Waitress as a
Windows Service · Linux adapter: Dockerfile-based containers · Metrics: agent
snapshots pushed to the Control Plane · Logs: local files + live/recent view in
the dashboard · Certificates: existing CRT/KEY filesystem paths only.

Not in V1: Prometheus, Loki, Grafana, ACME, Kubernetes, remote shell.

## Quickstart

```bash
cp .env.example .env
make setup
make up
```

- Dashboard: http://localhost:3000
- Control Plane health check: http://localhost:8000/health

Full instructions: [`docs/development.md`](docs/development.md).

## Status

- **Phase 1 — done:** monorepo foundation and architecture contract. `/health`
  works, the dashboard shows placeholder navigation, Celery connects to
  Redis, and the Go agent builds and prints its version.
- **Phase 2 — done:** PostgreSQL persistence layer. Full schema (users/roles,
  servers/agents, applications/releases/instances, deployments,
  domains/routing, health checks, secrets, metrics, audit log,
  notifications) via typed SQLAlchemy models and Alembic migrations, a
  repository/service layer so API routes stay free of raw DB logic, and
  validated state machines for deployment/instance/agent-command status. See
  [`docs/data-model.md`](docs/data-model.md).
- **Phase 3 — done:** authentication, roles, audit. Short-lived JWT access
  cookies + revocable, rotating, DB-backed refresh sessions; double-submit
  CSRF protection; Administrator/Operator/Viewer permission gating on
  routes; login/refresh/logout/me endpoints; an Administrator-bootstrap CLI;
  a dashboard login page, protected layout, and logout action; and audit
  logging for every login attempt, logout, and permission-gated mutation
  (never a password, token, or secret value). See
  [`docs/auth.md`](docs/auth.md).
- **Phase 4 — done:** server registration and the Agent protocol. Server
  create/list/view APIs; single-use, revocable, expiring enrollment tokens;
  an `/agents/enroll` REST call that exchanges a token for a long-lived
  connection credential; the Agent's outbound `/ws/agent` WebSocket
  (hello/heartbeat/command-event); heartbeat-based online/offline detection;
  a command envelope (idempotency key, expiry, correlation id) restricted to
  ten structured command types — no shell/free-form command exists anywhere
  in the protocol; commands queued while an agent is offline and delivered
  on reconnect; a fake Agent simulator (both in-process, for tests, and a
  standalone script for real-network manual testing); and dashboard screens
  for adding a server, enrollment instructions, and connection status. See
  [`docs/agent-protocol.md`](docs/agent-protocol.md).
- **Phase 5 — done:** the real cross-platform Go Agent. Enrollment CLI with
  secure local credential storage; a persistent WebSocket with
  reconnect/exponential-backoff, heartbeat, and a protocol-version
  compatibility check; real CPU/RAM/disk collection; a durable local
  command journal so a redelivered command is never executed twice; a
  restricted dispatcher (only `inspect_host` implemented — the other nine
  structured types are safely rejected as not-yet-implemented, never as
  arbitrary commands); safe per-command timeouts/cancellation; redacted
  structured logging; Windows Service install/start/stop
  (`golang.org/x/sys/windows/svc`) and a Linux systemd unit + install
  scripts. Verified against the real Control Plane on both a real Windows
  11 machine (installed and ran as an actual Windows Service) and a real
  Linux container (systemd-style `SIGTERM` shutdown). See
  [`docs/agent-runtime.md`](docs/agent-runtime.md).
- **Phase 6 — done:** application validation. `POST /applications/{id}/validate`
  runs domain-uniqueness, secret-existence, port-bookkeeping, certificate-pair
  (via the Gateway Manager), and live filesystem/interpreter/Docker/port
  checks on the target Agent — all through the existing structured command
  protocol, never a shell command. See [`docs/app-validation.md`](docs/app-validation.md).
- **Phase 7 — done:** the Windows Django/Waitress deployment adapter.
  `POST /applications/{id}/deploy` snapshots a release, creates a
  release-scoped venv, installs requirements, runs Django check/migrate/
  collectstatic, allocates one free port transactionally, and creates a
  low-privilege Windows Service running Waitress — every step recorded as a
  `DeploymentStep`/`DeploymentLog`. See [`docs/app-deployment.md`](docs/app-deployment.md).
- **Phase 8 — done:** the restricted Gateway Manager and central Nginx
  routing. One upstream per application (`least_conn`, keepalive, standard
  proxy headers) rendered from existing CRT/KEY paths and the application's
  currently-healthy instances; `nginx -t`-validated, atomically activated,
  and automatically restored to the last working config on any validation or
  reload failure. See [`docs/gateway-routing.md`](docs/gateway-routing.md).
- **Phase 9 — done:** manual replica scaling. `POST /applications/{id}/scale`
  reconciles the running instance count to a desired target within
  administrator-set `[min_replicas, max_replicas]` bounds: scale-up
  transactionally allocates ports, starts and health-checks each new
  instance before adding it to the gateway; scale-down drains (removes from
  the gateway), waits, then stops excess instances — never dropping active
  traffic. A race-safe per-application operation lock serializes
  deploy/scale/restart. See [`docs/scaling.md`](docs/scaling.md).
- **Phase 10 — done:** active health checks and bounded self-healing. A
  continuous background loop HTTP-polls every running instance at its
  configured cadence; a run of consecutive failures removes it from Nginx,
  attempts a controlled restart with health verification, and — if that
  fails — creates a replacement instance instead, bounded by a
  configurable attempt limit and cooldown (never an infinite loop) with an
  administrator notification once the limit is reached. See
  [`docs/self-healing.md`](docs/self-healing.md).
- **Phase 11 — done:** blue-green deployment and rollback.
  `POST /applications/{id}/releases` builds a new release on separately
  reserved ports, requires every new instance to pass its health gate
  before atomically switching Nginx, then drains and stops the previous
  release — a failed build, failed health check, or rejected Nginx config
  never touches the currently active release's traffic.
  `POST /applications/{id}/rollback` restores a previous successful release
  through the same health-gated switch, reusing its already-built code.
  Release retention, a fixed expand/migrate/contract advisory on every
  deploy, and a per-deployment timeline/failure reason round it out. See
  [`docs/blue-green-deployment.md`](docs/blue-green-deployment.md).
- **Phase 12 — done:** metrics and logs, without Prometheus, Loki, or
  Grafana. Short-term PostgreSQL retention (default seven days) and
  scheduled cleanup for the Agent's existing CPU/RAM/disk heartbeat
  snapshots, plus a bounded read API and dashboard summary cards/
  sparklines. A new `collect_logs` Agent command reads an instance's
  stdout/stderr with a byte- and line-bounded tail; a log-source registry,
  a bounded recent-log endpoint, and a Server-Sent-Events live tail expose
  it to the dashboard, with every line redacted for secrets/credentials
  before it leaves the Control Plane. Local instance logs rotate at each
  service start rather than growing unbounded forever. See
  [`docs/metrics-and-logs.md`](docs/metrics-and-logs.md).
- **Phase 13 — done:** the Linux Docker adapter. `deploy_release` builds a
  tagged image from a Dockerfile or pulls an immutable image reference;
  `start_instance` runs it as a container on a shared bridge network with
  administrator-set environment/resource limits and the application's
  secrets injected at start time; `stop_instance` stops and removes it. The
  same blue-green deploy/rollback, scaling, self-healing, and Nginx gateway
  routing every Windows application already gets, now adapter-agnostic
  across both. The Agent talks to the local Docker daemon directly over its
  Unix socket — fixed, structured Engine API calls, never a shelled-out
  `docker` command. See
  [`docs/linux-docker-adapter.md`](docs/linux-docker-adapter.md).
- **Phase 14 — done:** the dashboard, complete. Every implemented workflow
  is reachable without a direct API call: a real Overview, Deployments list
  and Deployment Details timeline, Certificates, Audit Log, and a new
  Administrator-only Users page, plus per-instance restart/stop buttons and
  a confirm-gated `[-]`/`[+]` scaling control on Application Details.
  Buttons a user's role doesn't permit are hidden, not just server-side
  rejected. Component tests (Vitest + React Testing Library) and an
  end-to-end suite (Playwright, run against the real dev stack) exist for
  the first time. See [`docs/dashboard.md`](docs/dashboard.md).
- **Phase 15 — done:** hardening, testing, packaging, release. Real
  encryption at rest for application secrets (Fernet, replacing a
  plaintext gap tracked since Phase 6); Agent credential revocation
  (previously only pre-enrollment tokens could be revoked); Control Plane
  restart recovery — a deployment or instance genuinely stuck mid-
  transition when the process died is reconciled to a clean failed state
  at the next startup (a real orphaned-state bug, found live during this
  phase, is fixed by this). A real concurrency test proves the operation
  lock is genuinely race-safe under simultaneous access; new CSRF/expired-
  token tests close a gap where only auth routes were checked. A real
  `make backup`/`make restore` rehearsal round-tripped the live database;
  a real concurrent load test sustained peak traffic with every instance
  staying healthy, while confirming user traffic never touches Healer's
  own database (the "two paths, kept separate" design, observed under
  load, not just asserted). Versioned, checksummed Agent release binaries
  for both platforms. Full install/uninstall, firewall, upgrade/rollback,
  troubleshooting, and operations-runbook docs, an API reference, and an
  explicit, re-verifiable confirmation that Prometheus/Grafana/Loki/ACME/
  Kubernetes/Buildpacks/remote-shell are all genuinely absent. See
  [`docs/release.md`](docs/release.md).

V1 is feature-complete per the master plan.
