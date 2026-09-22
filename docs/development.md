# Healer V1 — Development Guide

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2) — runs Postgres, Redis, Control
  Plane, Worker, Dashboard.
- Node.js 20+ and npm — dashboard.
- Python 3.12+ and pip — control-plane, worker, gateway-manager.
- Go 1.22+ — agent.
- GNU Make (Windows users: use Git Bash or WSL to get `make`; every target is a
  plain shell one-liner and can be copy-pasted directly if `make` isn't
  available).

## First-time setup

```bash
cp .env.example .env
make setup
```

`make setup` installs dependencies for every service (dashboard via npm,
control-plane/worker/gateway-manager via pip, agent via go mod download).

## Running the dev stack

```bash
make up          # builds and starts postgres, redis, control-plane, worker, dashboard
make logs        # tail logs
make down        # stop everything
```

Once up:

- Dashboard: http://localhost:3000
- Control Plane health check: http://localhost:8000/health
- Postgres: localhost:5432 (`healer` / see `.env`)
- Redis: localhost:6379

The Gateway Manager is intentionally **not** started by `make up` — see
[`docs/security-boundaries.md`](security-boundaries.md). Start it explicitly (for
local testing only) with:

```bash
docker compose -f deploy/docker-compose.yml --env-file .env --profile gateway up -d --build gateway-manager
```

## Database migrations

```bash
make migrate     # alembic upgrade head, run from services/control-plane
```

This applies the full schema and seeds the default roles (Administrator,
Operator, Viewer) — no separate seed step needed. See
[`docs/data-model.md`](data-model.md) for the entity list, constraints, state
machines, and rollback instructions (`alembic downgrade ...`).

Control-plane tests (`make test-control-plane` / `pytest` in
`services/control-plane`) run against a real Postgres — each test runs inside
a transaction that's rolled back afterward, so the dev database is left
untouched. Run `make migrate` at least once before `make test` so the schema
exists.

## Logging in

```bash
make bootstrap-admin   # creates the first Administrator from HEALER_BOOTSTRAP_ADMIN_EMAIL/_PASSWORD in .env
```

Then open http://localhost:3000 — you'll land on `/login`. See
[`docs/auth.md`](auth.md) for how sessions, CSRF, roles, and the audit log
fit together.

## Building and running the Agent

```bash
make build-agent      # produces agent/bin/healer-agent
make agent-version    # builds, then runs `healer-agent -version`
```

The agent is a standalone Go binary distributed to managed Windows/Linux servers;
it is not part of the Docker Compose dev stack.

## Formatting, linting, testing

```bash
make format   # black + ruff --fix (python), prettier (dashboard), gofmt (agent)
make lint     # ruff + black --check (python), next lint (dashboard), go vet (agent)
make test     # pytest (control-plane, worker), go test (agent)
```

## Repository layout

```
apps/dashboard/           Next.js + TypeScript admin dashboard
services/control-plane/   FastAPI control plane API (Postgres + Alembic)
services/worker/          Celery worker (Redis broker/backend)
services/gateway-manager/ Restricted Nginx-management service skeleton
agent/                    Go agent (cmd/healer-agent)
protocols/                Versioned JSON message schemas (control plane <-> agent)
deploy/                   Docker Compose + Nginx config templates
docs/                     Architecture, security boundaries, this guide
```
