# Healer V1 — Replica Scaling (Phase 9)

Turns the always-exactly-one-instance deploy pipeline (Phase 7) into a real
multi-instance system: manual replica counts within an administrator-set
range, transactional port allocation, health-gated scale-up, and
drain-before-stop scale-down.

## Replica bounds vs. the live scaling target

- `replicas.min` / `replicas.max` in `healer.yaml` (mirrored onto
  `Application.min_replicas`/`max_replicas`, same pattern as
  `port_range_start`/`end`) are the *allowed range* — set when the
  application is created/edited, validated against the port range
  (`replicas.max` can't exceed the number of ports available).
- `Application.desired_replicas` is the *live scaling target* —
  changed independently via `POST /applications/{id}/scale`, never by
  editing config. Editing config clamps it back into a newly-narrowed
  range rather than resetting it.

## Trigger

`POST /applications/{id}/scale {"desired_replicas": N}` (permission
`scale`) validates `N` against `[min_replicas, max_replicas]`, acquires the
application's operation lock (see below), and returns `202` immediately — the
actual work runs as a FastAPI BackgroundTask
(`app/services/scale_service.py:run_scale`). Poll `GET /deployments/{id}`
for step-by-step progress and `GET /applications/{id}/instances` for the
live instance table.

A scale operation reuses the Deployment/DeploymentStep/DeploymentLog tables
from the deploy pipeline — it's a Deployment against the application's
current release that only runs `start_instance`/`stop_instance`, never
`deploy_release`: it changes how many copies of the already-deployed release
are running, not the release itself.

## Operation locks

`Application.operation_lock`/`operation_lock_acquired_at`
(`app/services/lock_service.py`) serialize deploy/scale/restart so two
conflicting operations can never run against one application at once.
Acquisition is a single conditional `UPDATE ... WHERE operation_lock IS NULL
OR operation_lock_acquired_at < <stale cutoff>` — atomic under Postgres's
row-level locking, no separate advisory lock needed. A lock older than
`lock_service.STALE_LOCK_AFTER` (20 minutes) is treated as abandoned (e.g. a
crashed background task) and can be reacquired. Both `run_deployment` and
`run_scale` release the lock in a `finally` block, so it's always released
regardless of outcome.

## Scale-up: reserve, start, health-check, then route

For each new replica needed (`target - current`):

1. Allocate a port via the same transactional, SAVEPOINT-based allocator
   Phase 7 introduced (`deployment_service._allocate_instance`) — tries each
   port in the configured range, relying on the `uq_instances_server_id_port`
   unique constraint to catch a collision.
2. `start_instance` on the target Agent (the same generic, idempotent
   handler Phase 7 built — it was never hardcoded to one instance per app).
3. Health-check the new instance for real:
   `app/services/health_check_service.py:wait_until_healthy` polls the
   application's configured `health.path` at the configured
   `interval_seconds`, up to `healthy_threshold` consecutive successes
   (→ RUNNING) or `unhealthy_threshold` consecutive failures (→ UNHEALTHY).
   Every attempt is recorded as a `HealthCheckResult` (including
   `response_time_ms`), so the instance table has real health/latency data
   from the moment an instance starts. Blocking, run via `asyncio.to_thread`
   from the background task.
4. Only after every new instance in the batch has been started and
   health-checked does the scale operation sync the gateway once — only
   RUNNING instances are ever included in the Nginx upstream (see
   `docs/gateway-routing.md`), so a still-STARTING or UNHEALTHY instance is
   never routed to.

A failed `start_instance` or a health check that never passes marks that one
instance FAILED/UNHEALTHY (both are visible in the instance table and the
deployment's step log) without aborting the rest of the batch — each replica
is independent.

## Scale-down: drain before stop

For the `current - target` most-recently-created live instances (oldest
replicas are kept running):

1. Transition each to DRAINING and sync the gateway once — since only
   RUNNING instances are ever in the upstream, this is what actually stops
   *new* requests from reaching them. Requests already in flight on
   already-established connections are unaffected by an Nginx reload (it
   only affects new connections and DNS/upstream resolution going forward)
   and keep running independently.
2. Wait `scale_service.DEFAULT_DRAIN_TIMEOUT_SECONDS` (15s) — a fixed grace
   period for in-flight requests to finish naturally.
3. `stop_instance` on the target Agent (the same hard-stop handler Phase 7
   built) and transition to STOPPED.

## Instance table

`GET /applications/{id}/instances` returns every instance (any status) with
its port, server, state, latest health result, response time, and release
version — the dashboard's `InstanceTable` component polls this every 4s.

## Known simplifications (V1)

- The drain wait is a fixed timeout, not a real active-connection-count
  signal — there is no Agent capability to report "N connections still
  open" (would need a new Agent command/capability). A request that
  genuinely runs longer than the grace period is cut off when the instance
  is hard-stopped.
- `stop_instance` itself is still the same hard `Kill()`-then-remove Phase 7
  built, not a graceful in-process shutdown — the safety in scale-down comes
  entirely from removing the instance from the gateway *first* and waiting,
  not from the stop itself being gentler.
- A port once used by a FAILED (or STOPPED) instance is never reused — the
  allocator only ever looks for the next port with no existing row at all,
  matching Phase 7's existing deploy behavior. A server's port range slowly
  consumes itself across failed attempts; there is no reclaim/garbage
  collection in V1.
- `UpstreamGroup`/`UpstreamInstance` bookkeeping tables still aren't
  populated — the gateway continues to compute upstream membership directly
  from `Instance` rows at sync time (see `docs/gateway-routing.md`).
- Health checking here is strictly on-demand (once, right after an instance
  starts) to gate adding it to the gateway. Continuous background health
  monitoring of already-RUNNING instances, and automatically replacing an
  unhealthy one, is a later phase.
