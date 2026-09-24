# Troubleshooting guide

Organized by symptom. Every entry here reflects a real issue hit while
building and live-verifying Healer across its 15 phases, not a
hypothetical.

## "My dashboard/control-plane code changes aren't showing up"

Check whether the service you edited has a bind mount in
`deploy/docker-compose.yml`. `control-plane`, `worker`, and
`gateway-manager` do (`volumes: - ../services/...:/app`) — edits are live
immediately. **The dashboard does not** — its image is a `COPY` snapshot
taken at `docker build` time, so `docker compose exec dashboard ...`
against a container that hasn't been rebuilt since your last edit checks
stale code. This bit this exact project once (see `docs/dashboard.md`'s
closing section) — three real Phase 12/13 type errors sat undetected for
two phases because every "clean typecheck" was checking the old image.
Fix: run `npm install && npx tsc --noEmit` / `npm run lint` / `npm test`
with a host-installed Node toolchain against the real source, and
`docker compose build dashboard && docker compose up -d dashboard` to
refresh the actual running container before any live/e2e verification.

## Postgres "password authentication failed for user healer"

You (or a script) ran `docker compose` from inside `deploy/` directly,
or without `--env-file`, instead of from the repo root using the root
`docker-compose.yml` (a thin `include:` shim — see the Makefile's own
header comment). Compose's automatic `.env` discovery only looks in the
directory you invoke it from; run from `deploy/` and every
`${POSTGRES_PASSWORD:-changeme}`-style default silently falls back to
`changeme`, which doesn't match the real password already baked into the
Postgres data volume from first init — only the *newly recreated*
container (e.g. `control-plane`, whose `DATABASE_URL` is *computed* from
those env vars) breaks; `postgres` itself, if not recreated, keeps working
fine with its original real password, which is what makes this confusing.
Fix: always `docker compose -f docker-compose.yml --env-file .env ...`
from the repo root (exactly what `make up`/`make migrate`/etc. already do
— prefer the Makefile targets over raw `docker compose` for this reason).

## A Git-Bash / MSYS command mangles a path starting with `/`

Windows-only, Git Bash specific: `/tmp/foo`, `/var/run/docker.sock`, or
`/CN=...` (an openssl subject) passed to a command Git Bash thinks is a
Windows program gets silently rewritten to a `C:\Program Files\Git\...`
path. Prefix the command with `MSYS_NO_PATHCONV=1`. Not a Healer bug —
purely a Windows dev-environment quirk; a real Linux deployment target
never sees this.

## An elevated PowerShell command (installing/restarting a Windows Service)
## seems to hang or silently do nothing

`Start-Process -Verb RunAs` needs an interactive user physically present
to approve the UAC prompt — in any unattended/scripted/remote context
there's no one to click "Yes," and the prompt eventually times out with
"the operation was canceled by the user" (a real error message despite no
literal cancellation happening). This isn't fixable by retrying the same
call, and creating a SYSTEM-level scheduled task to route around it is a
persistence mechanism, not a legitimate workaround. The actual fix: have
someone with real interactive desktop access run the elevated command
directly (or write it to a `.ps1` file first and run `-File <path>` rather
than a long inline `-Command` string, which resolved genuine flakiness
even in properly-interactive sessions during this project).

## An Agent shows "offline" in the dashboard but the process is running

Check, in order:
1. Can the managed server reach the Control Plane's WebSocket port at all?
   (`docs/firewall-and-network.md`.) The Agent retries with exponential
   backoff (`agent/internal/transport`), so a transient network blip
   self-heals within a few reconnect attempts.
2. Is `agent_ws_public_url` (env var `AGENT_WS_PUBLIC_URL`) set to
   something the Agent can actually resolve/reach? A URL that only makes
   sense from inside the Control Plane's own Docker network (e.g. a
   Compose service name) will enroll successfully — the enrollment HTTP
   call and the returned WS URL are separate things — but every
   *reconnect* after that will fail silently from the Agent's point of
   view (it just retries forever against an unreachable host). This
   config only matters when an Agent runs somewhere that *can't* resolve
   your Control Plane's normal address the same way a browser can (e.g. a
   docker-outside-of-docker Agent joined to the compose network for
   testing) — revert it to whatever your Agents actually resolve once
   you're done with a setup like that.
3. Was the Agent's credential revoked (`POST /servers/{id}/agent/revoke`,
   Phase 15)? A revoked Agent's reconnect attempts fail authentication
   every time — re-enroll it with a fresh token.

## A deployment/scale/release operation is stuck "in_progress" forever

If the Control Plane process that started it crashed or was restarted,
nothing is left driving it — this used to mean it sat "in_progress" (and
its application's operation lock stayed held) until `lock_service`'s own
20-minute stale-lock timeout. As of Phase 15,
`app/services/reconcile_service.py` runs at every Control Plane startup
and fails any deployment still `in_progress` immediately, with a clear
`failure_reason`, and frees the lock right away — if you're on an older
version without this, either wait for the stale-lock timeout or manually
clear `Application.operation_lock` and transition the `Deployment` row to
`failed`.

## An instance is stuck in `starting`/`restarting`/`draining` and health
## checks never seem to look at it

The health-check loop (`health_monitor.tick()`) only ever polls instances
in `running` or `unhealthy` state — a transient state left behind by a
process that died mid-transition (same root cause as the stuck-deployment
case above) is invisible to it forever, not just delayed. Phase 15's
`reconcile_service.reconcile_stuck_instances` fixes this at startup too
(fails the instance, freeing that "slot" for a fresh deploy/scale to
replace it). This was a real bug found live during this project — a
`STARTING` instance from an interrupted self-healing replacement sat
orphaned for hours before the fix.

## Docker build/pull failing for a `linux-docker` application

Check the deploy's step log first (`GET /deployments/{id}`, or the
dashboard's Deployment Details page) — `docker_check` failing means the
Agent's host can't reach `/var/run/docker.sock` at all (see
`docs/linux-docker-adapter.md`); `build_or_pull` failing means the
Dockerfile/image reference itself is the problem (check the step's
message, which includes the Docker daemon's own error).

## Secrets: "secret value could not be decrypted"

`SECRET_ENCRYPTION_KEY` changed (or was never set consistently across
Control Plane instances/restarts) since the value was stored — every
stored secret was encrypted with whatever key was active at write time
(`app/core/secret_crypto.py`). There's no cross-key migration; re-set the
affected secret's value through the dashboard/API after fixing the key.

## Where to look next

- `docker compose logs -f control-plane` / `dashboard` / `worker` /
  `gateway-manager` for real-time application logs.
- The dashboard's own Audit Log page (Administrator role) for what
  administrative action preceded a problem.
- `docs/operations-runbook.md` for a structured incident-response
  checklist rather than a symptom lookup.
