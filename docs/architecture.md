# Healer V1 — Architecture

## 1. Two paths through the system

Healer deliberately separates two paths. Confusing them is the most common way a
deployment platform turns into a single point of failure for production traffic.

### Management path (control plane)

```
Administrator
   │  HTTPS
   ▼
Dashboard (Next.js)
   │  HTTPS / REST+JSON
   ▼
Control Plane API (FastAPI) ──────► PostgreSQL (state: servers, apps, releases,
   │        │                        instances, deployments, audit log)
   │        └────────────────────► Redis  (Celery broker/result backend)
   │                                   │
   │                                   ▼
   │                              Worker (Celery)  — long-running / async jobs:
   │                                   deploy, rollback, restart, port allocation
   │
   ├──── outbound secure WebSocket (wss://) ────► Agent (Go, on each managed
   │                                                Windows/Linux server)
   │
   └──── restricted internal call ─────────────► Gateway Manager (renders and
                                                   reloads the one central Nginx
                                                   config; never called by the
                                                   dashboard directly, never
                                                   exposed publicly)
```

The Control Plane is the only component that talks to Postgres, Redis, agents, and
the Gateway Manager. The dashboard never talks to agents, the database, or the
gateway manager directly — it only ever calls the Control Plane API.

### User-traffic path (production requests)

```
End user
   │  HTTPS
   ▼
Nginx (one central gateway, config owned by Gateway Manager)
   │
   ▼
Application instance(s) on a managed server
 (Waitress processes on Windows, Docker containers on Linux)
```

Healer's own services (dashboard, control plane, worker, agent) are **not** in this
path. If the control plane is down, already-deployed applications keep serving
traffic through Nginx exactly as before — Healer manages deployments, it does not
proxy live requests itself.

## 2. Components

| Component | Language/Framework | Responsibility |
|---|---|---|
| `apps/dashboard` | Next.js + React + TypeScript | Admin UI: servers, applications, deployments, health, certificates, audit log. Talks only to the Control Plane API. |
| `services/control-plane` | FastAPI | Source of truth. Owns the Postgres schema, issues jobs to Celery, holds agent WebSocket connections, is the only caller of the Gateway Manager. |
| `services/worker` | Celery (Python) | Executes durable, potentially long-running jobs (deploys, rollbacks, restarts, port allocation, health-driven remediation) off the request path. |
| `services/gateway-manager` | Restricted service (FastAPI skeleton in V1) | The *only* component permitted to write Nginx configuration and trigger a reload. Deliberately isolated — see `docs/security-boundaries.md`. |
| `agent` | Go binary | Runs on each managed Windows/Linux server. Connects outbound to the Control Plane over a secure WebSocket, executes the Windows/Linux V1 adapters, reports health and metrics snapshots. |
| `protocols` | JSON Schema | Versioned message contracts shared between the Control Plane and the Agent (and, indirectly, the Gateway Manager). |

## 3. Data stores

- **PostgreSQL** — durable state: registered servers, applications, releases,
  instances, deployments, certificate references, audit log entries. Managed with
  Alembic migrations from day one.
- **Redis** — Celery broker + result backend only. Not used as a primary datastore.

## 4. V1 adapters

- **Windows V1 adapter**: Django application processes run under Waitress,
  supervised as Windows Services. The Agent starts/stops/restarts these services
  and reports their state.
- **Linux V1 adapter**: applications are built from a Dockerfile and run as Docker
  containers. The Agent drives the local Docker daemon.

Both adapters are invoked by the Agent, never directly by the Control Plane —
the Control Plane only ever sends versioned protocol messages over the agent's
WebSocket connection.

## 5. Metrics and logs (V1 scope)

- **Metrics**: agents push basic snapshots (CPU, RAM, disk, per-instance status)
  directly to the Control Plane API on an interval. No Prometheus/Grafana in V1.
- **Logs**: local files on the managed server, tailed on demand / streamed live
  through the Agent → Control Plane → Dashboard for viewing. No Loki/ELK in V1.

## 6. Certificates (V1 scope)

Healer V1 only *references* existing certificate and key files already present on
disk (paths configured by the administrator). It does not issue, renew, or run
ACME/Let's-Encrypt flows. The Gateway Manager reads these paths when rendering
Nginx server blocks.

## 7. Explicitly out of scope for V1

Prometheus, Loki, Grafana, ACME/Let's Encrypt automation, Kubernetes, and any form
of remote interactive shell are not part of Healer V1 and must not be introduced
by later phases without a deliberate spec change.
