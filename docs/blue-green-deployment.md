# Healer V1 — Blue-Green Deployment and Rollback (Phase 11)

Turns "redeploy" into a health-gated, all-or-nothing switch between two full
sets of instances, instead of Phase 7's always-exactly-one-instance replace
or Phase 9's same-release scale up/down. The previous release keeps serving
until the new one has proven itself completely healthy; any failure at any
point leaves it exactly as it was.

## Two ways to update an already-deployed application

- `POST /applications/{id}/deploy` — the **one-time bootstrap only**: first
  release, one instance. Once `Application.active_release_id` is set, this
  endpoint refuses (409) — every later update goes through:
- `POST /applications/{id}/releases` — builds a brand-new release from the
  current source config and blue-green switches to it.
- `POST /applications/{id}/rollback {"release_id": "..."}` — runs the exact
  same health-gated switch against a **previously-successful** release's
  already-built code (no rebuild — its `release_dir`/`venv_python` are still
  on disk from when it was originally deployed).

Both return `202` with `{deployment_id}` immediately; poll
`GET /deployments/{deployment_id}` for the step-by-step timeline (or
`GET /applications/{id}/instances` for live per-instance state) — the
dashboard's `ReleaseTimeline` renders this chronologically with each step's
status and duration.

## Why the port range must be sized for it

A blue-green switch runs the new release's instances *alongside* the old
release's, on **separately reserved ports** — the same transactional
allocator Phase 7/9 use (`_allocate_instance`) just skips whatever ports the
old release's instances already hold. This means `ports.start`/`ports.end`
must cover at least `2 × desired_replicas` ports for a switch to succeed —
if a healer.yaml is only sized for exactly `desired_replicas` ports, a
blue-green deploy will fail outright at the port-allocation step (visible in
the deployment's step log), by design rather than silently reusing a port
still held by a live old instance.

## The all-or-nothing health gate

Every one of the new release's instances must individually pass
`health_check_service.wait_until_healthy` (the same configured
path/interval/timeout/thresholds as everywhere else) before *any* traffic
moves. A single failure — anywhere in the batch — aborts the whole switch:
every new instance started so far (healthy or not) is stopped immediately,
since none of them were ever added to Nginx, so no live traffic was ever at
risk. `active_release_id` and the old release's instances are never
touched. This is what makes "a bad release never receives traffic" true
regardless of which replica in the batch fails, or how far into starting
the batch the failure happens.

## The atomic switch, and what happens if Nginx rejects it

`gateway_service` now filters an application's upstream by
`Instance.release_id == Application.active_release_id` (falling back to
"every RUNNING instance" for an app from before Phase 11, or one that's
never blue-green deployed) — so flipping `active_release_id` and syncing
the gateway *is* the entire cutover, in one Nginx reload, not a gradual mix
of old and new. The sequence is: flip `active_release_id` → `sync_gateway`.
If the Gateway Manager rejects the new config (`nginx -t` failure) or the
reload itself fails, Phase 8's own atomic-restore already put Nginx back on
the previous working config — this module additionally reverts
`active_release_id` back to the old release so the database matches what's
actually being routed, then stops the new release's instances (they were
never serving) and marks the deployment FAILED with the Gateway Manager's
own error text as `failure_reason`. The old release was never touched.

## Only after the switch: drain and stop the old release

Once the new release is confirmed serving (gateway synced successfully),
every RUNNING instance of the *old* release is marked DRAINING (already
excluded from the new upstream at this point, matching Phase 9's
scale-down), given a grace period for in-flight requests on existing
connections to finish, then stopped.

## Release retention

`Application.release_retention_count` (default 5) bounds how many past
`READY` releases are kept — after each successful switch, older ones beyond
that count are pruned (the currently active release is never pruned,
regardless of count). Pruning is database bookkeeping only in V1 — see
"Known simplifications" below.

## Database migrations: expand/migrate/contract

Every blue-green deploy runs the new release's migrations against the
**same, shared database** while the old release may still be — briefly —
serving requests, and the new release's own instances are being health-gated
before the cutover. `POST /applications/{id}/releases` always returns a
`warnings` array with a fixed advisory (`release_service.MIGRATION_WARNING`)
because there is no automated way in V1 to tell whether a given migration is
actually safe under that overlap — this is a process practice, not something
Healer verifies for you:

- **Expand**: a migration in *this* release may only ADD — a nullable
  column, a new table, a new index. Never rename or drop anything the
  *previous* release's code might still be executing against during the
  health-gate/switch window.
- **Migrate**: application code in this release starts writing/reading the
  new shape (e.g. dual-writing an old and new column) while both are
  present.
- **Contract**: only in a *later* release, once you are certain no running
  instance depends on the old shape anymore, does a migration actually
  remove it.

A migration that violates this (e.g. `DROP COLUMN` in the same release that
stops writing to it) can break the *old* release the instant the new
release's `migrate` step runs — before the switch even happens — since
Django migrations apply to the one shared database immediately, not per
release. Healer cannot detect this for you; follow the practice above.

## Known simplifications (V1)

- Release retention prunes database rows only — the old release's
  `release_dir`/venv on disk are not deleted. Real disk cleanup would need a
  new Agent capability (deleting an arbitrary path), which deserves its own
  focused safety design rather than being folded into this phase.
- The migration warning is a fixed, always-shown advisory, not an automated
  safety analysis of the actual migration — see above.
- A replacement/rollback still uses the same fixed `DEFAULT_DRAIN_TIMEOUT_SECONDS`
  grace period (not a real active-connection-count signal) that Phase 9's
  scale-down and Phase 10's self-healing already document as a known
  simplification.
- Only one blue-green switch (or rollback) may be in flight per application
  at a time, enforced by the same operation lock deploy/scale/heal share.
