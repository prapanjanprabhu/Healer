# Healer V1 — Authentication, Roles, Audit

## Sessions

- **Access token**: a short-lived (15 min default) JWT, HMAC-signed with
  `CONTROL_PLANE_SECRET_KEY`, carried in the `healer_access` cookie
  (HttpOnly, `Secure` per `COOKIE_SECURE`, `SameSite=Lax`). Stateless — not
  individually revocable, but expires quickly, so revocation happens at the
  refresh boundary.
- **Refresh session**: a random opaque token (only its SHA-256 hash is
  stored, in `refresh_sessions`), carried in the `healer_refresh` cookie
  (HttpOnly, scoped to `/auth`), default 14-day TTL. Fully revocable — the
  DB row is the source of truth.
- **Rotation**: every `POST /auth/refresh` revokes the presented refresh
  token and issues a new one (`app/services/auth_service.rotate_refresh_session`).
  Presenting an already-revoked token is treated as a possible theft/replay
  and revokes every active session for that user, forcing re-login
  everywhere — see `tests/test_auth.py::test_refresh_rotates_tokens_and_rejects_replay_of_the_old_one`.
- **Logout**: revokes the current refresh session and clears all three
  cookies (`app/api/routes/auth.py::logout`).

## CSRF

The `healer_csrf` cookie is deliberately **not** HttpOnly — same-origin JS
(the dashboard) reads it and echoes it back as the `X-CSRF-Token` header on
every mutating request; a cross-site page can trigger a cookie-bearing
request but can't read the cookie to produce a matching header
(`app/api/deps.py::verify_csrf`). Applied to `/auth/refresh`, `/auth/logout`,
and any route that mutates state on the strength of the auth cookies (e.g.
`POST /deployments/{id}/actions/deploy`). `/auth/login` is exempt — it
requires the actual password, so there's no cookie-based session yet to
forge.

## Roles and permissions

Seeded by migration `0003_seed_default_roles` (see
[`docs/data-model.md`](data-model.md)): **Administrator**, **Operator**,
**Viewer**. The permission matrix lives in
[`app/domain/permissions.py`](../services/control-plane/app/domain/permissions.py):

| Role | Permissions |
|---|---|
| Administrator | everything (`"*"`) |
| Operator | `view`, `deploy`, `scale`, `restart`, `stop`, `rollback` — no user/security administration |
| Viewer | `view` only |

Routes declare what they need with `Depends(require_permission("deploy"))`
etc. (`app/api/deps.py`); a request without the right permission gets `403`,
one without a valid session gets `401`. Dependency order matters here:
auth is resolved before CSRF, so an unauthenticated request reliably gets
`401` rather than a `403` CSRF mismatch that would be true but misleading.

## Bootstrap

The first Administrator account can't be created through the API (there's
no user yet to authorize it), so it's a CLI command instead:

```bash
make bootstrap-admin   # reads HEALER_BOOTSTRAP_ADMIN_EMAIL / _PASSWORD from .env
# or
cd services/control-plane && python -m app.cli.bootstrap_admin --email you@example.com --password '...'
```

Idempotent — does nothing if that email already exists. Requires
`alembic upgrade head` to have run first (the Administrator role must
already be seeded).

## Audit logging

Every login attempt (success and failure), logout, and permission-gated
mutation writes an `AuditLog` row (`app/services/audit_service.py`) — see
`docs/data-model.md` for the table shape. **Never** log a password, token,
or secret value: failed-login entries record only `{"reason":
"invalid_credentials"}`, never the attempted password; the bootstrap CLI
prints the new admin's email, never its password. `tests/test_auth.py::test_login_records_audit_entries_without_leaking_the_password`
asserts this directly.

## Dashboard

- `src/app/login/page.tsx` — email/password form, posts to the Control
  Plane with `credentials: "include"`.
- `src/middleware.ts` — runs server-side on every request; forwards the
  incoming cookie header to `GET /auth/me` and redirects to `/login` if it
  isn't `200`.
- `src/app/(dashboard)/layout.tsx` — a second, defense-in-depth auth check
  (same `/auth/me` call) wrapping every page under the `(dashboard)` route
  group; renders the sidebar with the current user's email/roles and a
  logout button.
- `src/components/LogoutButton.tsx` — reads the CSRF cookie
  (`src/lib/csrf.ts`) and calls `POST /auth/logout`.

Two different Control Plane URLs are used on purpose
(`src/lib/config.ts`): `NEXT_PUBLIC_CONTROL_PLANE_URL` for the browser
(`http://localhost:8000`), and `CONTROL_PLANE_INTERNAL_URL` for the
dashboard's own server-side code (`http://control-plane:8000`, the Compose
service hostname) — inside Docker, "localhost" from the dashboard
container's perspective is the dashboard container itself, not the Control
Plane.
