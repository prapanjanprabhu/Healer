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

Deployment behavior (actually deploying, routing, and health-driven
remediation) is not implemented yet — that's the API/worker logic layered on
top of this schema in a later phase.
