# Gateway Manager

Restricted, internal-only service. It is the **only** component permitted to
render Nginx configuration and reload the one central Nginx installation that
Healer routes production traffic through.

Read [`docs/security-boundaries.md`](../../docs/security-boundaries.md) before
changing anything here. In short:

- Never bind this service to a public interface (`GATEWAY_MANAGER_HOST`
  defaults to `127.0.0.1`).
- Never call it from the dashboard — only the Control Plane calls it, over the
  internal network, authenticated with `GATEWAY_MANAGER_SHARED_SECRET`.
- It has no database access and no agent connections.

## Phase 1 scope

Only a `/health` endpoint and a stubbed `POST /reload` (returns `501 Not
Implemented`). Actual Nginx template rendering and reload logic are added when
deployment behavior is implemented.
