# API reference (V1, final)

Every route the Control Plane exposes, generated from the actual route
files (`services/control-plane/app/api/routes/`), not written from memory.
Base path is whatever `CONTROL_PLANE_PUBLIC_URL`/`NEXT_PUBLIC_CONTROL_PLANE_URL`
resolve to (`http://localhost:8000` in dev). Every route except `/health`
and `/auth/login` requires the session cookies `POST /auth/login` sets;
every mutating route additionally requires the `X-CSRF-Token` header (see
`docs/auth.md`). Permission names in parenthesis match
`app/domain/permissions.py`'s matrix — Administrator implicitly holds
every permission.

## Health

- `GET /health` — liveness, no auth.

## Auth (`docs/auth.md`)

- `POST /auth/login` — no auth required.
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me` — current user + roles.
- `POST /auth/change-password` — self-service (Phase 15).

## Servers (`docs/agent-protocol.md`)

- `GET /servers` (`view`)
- `GET /servers/{id}` (`view`)
- `POST /servers` (`manage_servers`)
- `POST /servers/{id}/enrollment-tokens` (`manage_servers`)
- `GET /servers/{id}/enrollment-tokens` (`manage_servers`)
- `DELETE /servers/{id}/enrollment-tokens/{token_id}` (`manage_servers`)
- `POST /servers/{id}/agent/revoke` (`manage_servers`) — Phase 15.
- `GET /servers/{id}/metrics` (`view`) — Phase 12.

## Agents (`docs/agent-protocol.md`)

- `POST /agents/enroll` — exchanges a single-use enrollment token for a
  long-lived credential (called by the Agent CLI, not the dashboard).
- `GET /agents/{id}/commands`
- `GET /agents/{id}/commands/{command_id}`
- `POST /agents/{id}/commands`

## Applications (`docs/app-deployment.md`, `docs/scaling.md`, `docs/blue-green-deployment.md`)

- `POST /applications/parse-yaml` (`view`) — validates a pasted
  `healer.yaml` without saving it.
- `GET /applications` (`view`)
- `GET /applications/{id}` (`view`)
- `POST /applications` (`deploy`)
- `PATCH /applications/{id}` (`deploy`)
- `POST /applications/{id}/validate` (`view`) — `docs/app-validation.md`.
- `POST /applications/{id}/deploy` (`deploy`) — first-time bootstrap deploy.
- `POST /applications/{id}/gateway/sync` (`deploy`) — `docs/gateway-routing.md`.
- `POST /applications/{id}/scale` (`scale`)
- `POST /applications/{id}/releases` (`deploy`) — blue-green switch.
- `POST /applications/{id}/rollback` (`rollback`)
- `GET /applications/{id}/releases` (`view`)
- `GET /applications/{id}/instances` (`view`)
- `POST /applications/{id}/instances/{instance_id}/restart` (`restart`) — Phase 14.
- `POST /applications/{id}/instances/{instance_id}/stop` (`stop`) — Phase 14.
- `POST /applications/{id}/secrets` (`deploy`) — write-only.
- `GET /applications/{id}/secrets` (`view`) — keys only, never values.
- `DELETE /applications/{id}/secrets/{key}` (`deploy`)

## Deployments (`docs/app-deployment.md`)

- `GET /deployments` (`view`) — list, richer since Phase 14 (application
  name, kind, timestamps).
- `GET /deployments/{id}` (`view`) — full timeline (steps/logs/instances).
- `POST /deployments/{id}/actions/deploy` (`deploy`)

## Logs (`docs/metrics-and-logs.md`)

- `GET /applications/{id}/log-sources` (`view`)
- `GET /applications/{id}/instances/{instance_id}/logs` (`view`) — bounded
  recent read.
- `GET /applications/{id}/instances/{instance_id}/logs/stream` (`view`) —
  Server-Sent Events live tail.

## Notifications

- `GET /notifications` (own + broadcast)
- `POST /notifications/{id}/read`

## Users (`manage_users` — Administrator only; Phase 14)

- `GET /users`
- `GET /users/roles` — the fixed V1 role set.
- `POST /users`
- `PATCH /users/{id}/roles`
- `POST /users/{id}/deactivate`
- `POST /users/{id}/activate`

## Audit log (`view_audit` — Administrator only; Phase 14)

- `GET /audit-log` — filterable by `action`/`target_type`, bounded `limit`.

## WebSocket

- `WS /ws/agent` — the Agent's one outbound connection (hello/heartbeat/
  command-event, `docs/agent-protocol.md`). Never called by the dashboard
  or a human directly.

## What's intentionally absent

No endpoint accepts a shell command, a raw file path outside a
validated/structured field, or arbitrary SQL. No endpoint returns a
secret's decrypted value. See `docs/security-boundaries.md`.
