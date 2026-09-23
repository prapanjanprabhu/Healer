# Healer V1 — Active Health Checks and Bounded Self-Healing (Phase 10)

Turns the on-demand, scale-up-only health checking from Phase 9 into a
continuous background loop that detects a failing instance on its own and
attempts to repair it, within firm limits — never an infinite restart loop.

## Where it runs

`app/services/health_monitor.py:run_forever()` is a single asyncio
background task started from `app/main.py`'s FastAPI lifespan, gated by
`settings.health_monitor_enabled` (off by default, so the test suite never
runs it — `HEALTH_MONITOR_ENABLED=true` in the real `.env`). It must live in
the Control Plane's own process: healing sends Agent commands and waits for
their result via `command_service`'s `asyncio.Event` coordination, which —
like every other command in this V1 — only works within the process holding
the WebSocket connection.

## Configurable health check

`HealthCheck` (one row per application, from `healer.yaml`'s `health:`
section) now also carries:

- `expected_status` — if set, the health check requires this exact HTTP
  status; unset (the default, and all of Phase 9's behavior) accepts any
  non-5xx response.
- `max_restart_attempts` (default 3) / `restart_cooldown_seconds`
  (default 30) — the self-healing bounds described below.

## Detection

Every tick (`health_monitor.POLL_INTERVAL_SECONDS`, 5s):

1. For each RUNNING instance whose configured `interval_seconds` has
   elapsed since its last result, a real HTTP GET is made and a
   `HealthCheckResult` is recorded (healthy/detail/response time) — the
   same persistence and thresholds Phase 9 introduced, just run
   continuously instead of only right after a scale-up.
2. A run of `unhealthy_threshold` consecutive failures hands the instance
   to `self_healing_service.handle_unhealthy_instance` — guarded by the
   same per-application operation lock deploy/scale use (`lock_service`,
   operation name `"heal"`), so healing can never race a deploy or scale
   in progress; if the lock is held, healing is simply retried next tick.
3. Every already-UNHEALTHY instance is *also* revisited each tick (no HTTP
   poll needed — it's already known down) so a healing attempt deferred by
   `restart_cooldown_seconds` gets retried once that cooldown passes,
   rather than being stuck forever once it's no longer RUNNING and so
   invisible to the poll in step 1.

## Remediation (`self_healing_service.handle_unhealthy_instance`)

1. **Remove from Nginx before doing anything else.** Transitioning RUNNING
   → UNHEALTHY *is* the removal — `gateway_service` only ever includes
   RUNNING instances in the rendered upstream, exactly as it did for
   Phase 9's DRAINING scale-down. An `instance.removed_unhealthy` audit
   record is written and the gateway is synced.
2. **Cooldown / attempt-limit check.** If a cooldown from the last attempt
   hasn't elapsed, do nothing this tick (retried later). If
   `healing_attempts` has already reached `max_restart_attempts`, give up
   immediately (see below) without attempting another restart.
3. **Controlled restart, then verify.** UNHEALTHY → RESTARTING, then
   re-issue `start_instance` for the *same* `service_name`/port — the
   Agent's own idempotent handling (an existing service under that name is
   stopped and removed before a fresh one is created) *is* the restart; no
   new Agent capability was needed. `health_check_service.wait_until_healthy`
   then polls the restarted instance for real, at the configured
   thresholds, exactly as it does for a fresh scale-up instance.
4. **Recovered:** RESTARTING → RUNNING, `instance.recovered` audit record,
   gateway synced again to re-add it to Nginx.
5. **Restart failed, or never came back healthy:** RESTARTING → FAILED
   (`instance.restart_failed` audit record, `failure_reason` set) and a
   **replacement** instance is created on a new port via the same
   transactional allocator Phase 7/9 use — started and health-checked the
   same way a scale-up instance is, then added to Nginx once healthy. The
   replacement carries the original's `healing_attempts` count forward, so
   a whole failing "lineage" (one instance plus however many replacements
   it took) stays bounded by one `max_restart_attempts` limit, not reset by
   every replacement.
6. **Giving up** (limit reached, no Agent connected, no release to restart
   from, or a replacement itself fails): the instance is left FAILED with a
   human-readable `failure_reason`, an `instance.recovery_failed` audit
   record is written, and an unscoped `Notification` (visible to every
   Administrator, `notification_type="self_healing_gave_up"`) is created —
   `GET /notifications`. No further attempts are made for that instance;
   this is what bounds the loop.

## Dashboard

`GET /applications/{id}/instances` now also returns `failure_reason` and
`healing_attempts` per instance — `InstanceTable` shows the failure reason
inline for any FAILED/UNHEALTHY row. `GET /notifications` lists
self-healing (and future) alerts for the current administrator plus every
broadcast one.

## Known simplifications (V1)

- "Restart" is `start_instance` re-issued for the same port — there is no
  separate Agent-level graceful-restart primitive; this reuses exactly the
  idempotent create-or-replace behavior `start_instance` already had.
- The monitor loop is a single in-process asyncio task, not a distributed
  scheduler — matches this whole V1's "one Control Plane instance" model
  (see `docs/agent-protocol.md`).
- A replacement is attempted exactly once per healing event; if the
  replacement itself fails to start or never becomes healthy, Healer gives
  up on it immediately rather than trying a second replacement in the same
  event (the overall `max_restart_attempts` bound still applies across
  ticks if it later fails again).
- No cross-instance correlation ("3 instances failed within a minute, this
  might be a bad release") — each instance heals independently.
