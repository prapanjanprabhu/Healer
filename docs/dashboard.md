# The dashboard, complete (Phase 14)

Every implemented V1 workflow is now reachable through the dashboard —
no direct API call needed for anything an administrator, operator, or
viewer does day to day.

## What Phase 14 added

**New pages**: a real Overview (server/application/deployment/notification
summary cards, not the Phase 1 placeholder), a real Deployments list with
application name/kind/timestamps and links into a new Deployment Details
page (timeline, touched instances, log), a real Certificates page
(cross-application domain/cert/key reference list), a real Audit Log page,
a new Users page (Administrator-only: create accounts, change roles,
activate/deactivate), and a new Settings page (self-service password
change, plus read-only operational defaults).

**New backend endpoints** the above needed and didn't have:
`POST/PATCH /users`, `/users/{id}/roles`, `/users/{id}/activate|deactivate`
(`app/services/user_service.py`), `GET /audit-log` (`app/services/audit_service.py`'s
new `list_entries`), a richer `GET /deployments` (application name, kind,
timestamps — it used to return only `{id, application_id, status}`), and
`POST /auth/change-password`. Also two we hadn't built at all until an
administrator needed a UI button for them: `POST
/applications/{id}/instances/{instance_id}/restart` and `.../stop`
(`app/services/instance_service.py`) — manual, single-instance actions
distinct from scaling (changes replica *count*) and self-healing
(automatic, health-check-triggered). Both hold the application's operation
lock and require the same `restart`/`stop` permissions
`app/domain/permissions.py` already anticipated in Phase 1 but nothing had
used yet. Restarting a healthy `RUNNING` instance needed one state-machine
change too: `RUNNING -> RESTARTING` wasn't previously a legal transition
(only `UNHEALTHY -> RESTARTING`, self-healing's own path).

**Application Details** now has a `[-]`/`[+]` stepper for the desired
replica count with an explicit "Change to N" -> confirm/cancel step before
it calls the scale API (previously: a bare number input and one button,
already-live-progress display was the only thing done right), and the
instance table gained per-row Restart/Stop buttons — confirmed before
firing, hidden entirely for a Viewer, disabled for an instance not in a
restartable/stoppable state.

**Permission-aware UI**: `src/lib/permissions.ts` mirrors the Control
Plane's `ROLE_PERMISSIONS` matrix; `CurrentUserProvider`/`useHasPermission`
(`src/components/CurrentUserProvider.tsx`) make the already-authenticated
user's roles (fetched server-side in the dashboard layout, previously only
ever displayed in the sidebar) available to every client component, so a
Viewer never sees a scale/restart/stop control it isn't allowed to use, and
the sidebar itself hides the Users/Audit Log links for anyone without
`manage_users`/`view_audit`. This didn't exist at all before Phase 14 — every
button was visible to every authenticated user regardless of role, with
enforcement happening only server-side.

**Loading/empty/offline/permission-denied states**: Servers, Applications,
Overview, Deployments, and Certificates now all distinguish "the Control
Plane is unreachable" from "there's genuinely nothing here yet" (previously
several list pages silently treated a failed fetch as an empty list). Audit
Log and Users both render a plain-language permission-denied message for a
403 rather than an empty table.

**Responsive/accessible groundwork**: `globals.css` had zero `@media`
queries and no interactive-element focus styling before this phase (one
rule even did `outline: none` on inputs with no visible replacement). Added:
a sub-768px breakpoint that turns the fixed-width sidebar into a wrapping
top bar and drops the desktop content padding/max-width, a consistent
`:focus-visible` ring on every interactive element, a skip-to-content link,
and `aria-live="polite"` on the panels that update themselves on a timer
(ScalePanel's progress list, DeploymentDetailView) so a screen reader
announces progress instead of silently re-rendering text.

## Test infrastructure (built from scratch — none existed before)

- **Component tests**: Vitest + React Testing Library
  (`vitest.config.ts`/`vitest.setup.ts`). Covers `lib/permissions.ts`'s
  matrix directly, `Sparkline`'s empty/populated render, and — the one that
  matters most here — `ScalePanel`'s stepper bounds and its confirm-before-
  apply gate (asserts the API is *not* called until "Confirm" is clicked,
  and that "Cancel" reverts cleanly). Run: `npm test`.
- **End-to-end**: Playwright (`playwright.config.ts`, `e2e/admin-workflow.spec.ts`),
  run against the real dev stack (dashboard + Control Plane), not a mocked
  backend — genuinely signs in, registers a server, describes an
  application, creates a user, and confirms it shows up in the real audit
  log, all through the actual rendered UI. It deliberately does **not**
  drive an actual deploy/scale/health-check/rollback round trip: that needs
  a real connected Agent on a real target, which a repeatable e2e suite
  can't provision for itself — that path stays covered by the Control
  Plane's own hermetic test suite and by this project's per-phase manual
  live verification. Run: `npm run test:e2e` (needs `docker compose up`
  running first, and reads `E2E_ADMIN_EMAIL`/`E2E_ADMIN_PASSWORD` for an
  existing Administrator account).

## A note on how this phase was actually built

The dashboard's Docker Compose service has no bind mount (unlike the
Control Plane's) — its image is a `COPY` snapshot taken at `docker build`
time. Every `docker compose exec dashboard <tsc/lint/build>` run earlier in
this project was silently checking whatever code existed at the *last
image build*, not the current source on disk. This phase's verification
runs went straight to the real bug: `npx tsc --noEmit` against the actual
host source turned up three real `noUncheckedIndexedAccess` errors in
Phase 12/13 code that every prior "clean typecheck" claim had missed
entirely. All three are fixed. Going forward, dashboard verification in
this project runs via a host-installed Node toolchain
(`apps/dashboard: npm install`) rather than through the stale container,
and the real Docker image is rebuilt (`docker compose build dashboard`)
whenever the running container needs to reflect current code — which is
also why this phase's live e2e verification was run twice: once against a
host `next dev` server, and a second time against the freshly rebuilt real
container, to confirm the actual deployed artifact behaves identically.
