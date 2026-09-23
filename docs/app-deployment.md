# Application deployment (Windows / Django+Waitress)

Phase 7 turns a saved, validated application into one running instance. It
never touches Nginx and never runs more than one instance per deploy — see
`docs/healer-yaml.md` and `docs/app-validation.md` for what came before.

## Trigger

`POST /applications/{id}/deploy` (permission `deploy`) returns `202` immediately
with `{deployment_id, release_id, instance_id, port, service_name}`. The
actual work happens in the background; poll `GET /deployments/{id}` for
live progress (steps and logs are written incrementally, not just at the end).

Pre-flight checks (`app/services/deployment_service.py:start_deployment`) run
synchronously and fail the trigger request itself with `409` if:
- the adapter isn't `windows-waitress-service` (the only one implemented),
- the target server has no currently-connected Agent,
- the application has no source configured,
- every port in the configured range is already taken by another instance
  on that server (checked transactionally — see below).

## Port allocation

One port is allocated by trying each port in `ports.start..ports.end` in
order, inserting the `Instance` row inside its own SAVEPOINT. A collision
(`uq_instances_server_id_port`) rolls back just that attempt and moves to
the next port — this is what "transactional" means here: correctness comes
from the database constraint, not from application-level locking, so it's
safe even if two deploys race for the same server.

## The pipeline

Two structured Agent commands, sent in sequence, each producing a
`{"ok": bool, "steps": [{"name", "status", "message"}, ...]}` result that is
persisted verbatim into `DeploymentStep`/`DeploymentLog` rows:

1. **`deploy_release`** — snapshots the source into a versioned release
   directory, excluding virtualenvs/caches/`.git`/secrets and the
   static/media/log directories (those get symlinked to per-application
   *shared* storage instead, so they survive across releases). Then: create
   a venv, `pip install -r requirements.txt`, `manage.py check`, `manage.py
   migrate` (under a simple exclusive file lock per application — a second
   concurrent deploy waits, then fails clearly rather than racing), and
   `manage.py collectstatic`. Stops at the first failing step; every step
   still gets recorded, later ones marked `skipped`.
2. **`start_instance`** — only sent if (1) fully succeeded. Grants the
   low-privilege `NT AUTHORITY\LocalService` account access to the app's
   data directory, then installs and starts a Windows Service named
   deterministically as `Healer-<app-slug>-<port>` (e.g.
   `Healer-rit-academic-erp-9034`) running Waitress against the release's
   own venv, with stdout/stderr captured into managed log files under the
   shared `logs` directory.

Neither command ever carries a shell command string — every field is
structured (paths, a version string, a wsgi module name); the Agent builds
its own `exec.Command` argument arrays locally. See
`agent/internal/dispatcher/deploy_release.go` and `start_instance.go`.

## State

`Release.status`: `PENDING` → `BUILDING` → `READY`/`FAILED`.
`Instance.status`: `PENDING` → `STARTING` (deploy_release succeeded) →
`RUNNING`/`FAILED` (start_instance's outcome).
`Deployment.status`: `PENDING` → `IN_PROGRESS` → `SUCCEEDED`/`FAILED`.

## Known simplifications (V1)

- Only `source.type: folder` is implemented on the Agent; a `git` source
  reports a clean `ok: false` "not yet implemented" result rather than an
  error.
- The Windows Service Healer installs to host Waitress is a hard `Kill()`
  on stop, not a graceful drain.
- No zero-downtime rollout, no rollback, no health-check-gated promotion —
  `Deployment.zero_downtime`/`instance_count` exist in the schema for a
  later phase but this one always deploys exactly one instance.
