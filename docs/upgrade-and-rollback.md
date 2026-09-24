# Upgrading and rolling back Healer itself

Distinguish this from an *application's* blue-green release/rollback
(`docs/blue-green-deployment.md`) — this document is about upgrading the
Healer platform's own components (Control Plane, dashboard, Gateway
Manager, worker, and the Agent binaries), not an application deployed
through it.

## Order of operations for an upgrade

1. **Back up first.** `make backup` (see `docs/backup-and-restore.md`).
   Every schema change ships as an Alembic migration
   (`services/control-plane/migrations/`) — a backup taken immediately
   before is what you'd restore if a migration goes wrong.
2. **Read the migration list** between your current version and the target
   (`alembic history`) for anything requiring manual attention — V1's
   migrations are all additive (new columns/tables, `server_default` for
   backfill) by the same expand/migrate/contract discipline
   `docs/blue-green-deployment.md` documents for application deploys, so a
   plain `alembic upgrade head` is expected to be safe, but always check.
3. **Control Plane / dashboard / Gateway Manager / worker**: these are
   built from source via Docker Compose
   (`deploy/docker-compose.yml` — no pre-built version-tagged images exist
   for these four in V1, see `docs/release.md`). Pull the new source,
   then:
   ```
   make migrate     # alembic upgrade head
   make build       # docker compose build
   make restart     # docker compose down && up -d
   ```
   The Control Plane's own startup reconciliation
   (`app/services/reconcile_service.py`) fails-safe any deployment that
   was genuinely `in_progress` when the old process stopped, and frees its
   application's operation lock immediately — you don't need to manually
   clean up an in-flight deploy/scale/release switch that was running at
   the moment you restarted.
4. **Agents**: upgrade independently of the Control Plane, on whatever
   schedule you like — see `docs/windows-agent-install.md` /
   `docs/linux-agent-install.md`'s "Upgrading in place" sections. An older
   Agent talking to a newer Control Plane (or vice versa) is expected to
   keep working within one protocol major version
   (`agent/internal/version.MinCompatibleProtocolVersion` — the Agent
   refuses to run against a Control Plane reporting an incompatible
   version rather than guess).
5. **Verify** before considering the upgrade done: `GET /health` on the
   Control Plane, a real login, every Agent still shows online, and — if
   you have a non-critical application to spare — a real deploy/scale
   round trip through the dashboard.

## Rolling back a Healer upgrade

There is no single `make rollback` for the platform itself (unlike an
application's blue-green rollback, which V1 automates) — because
Control-Plane upgrades are source-rebuilds, not swappable images, a
platform rollback is: check out the previous version's source, `make
migrate` (if the new version's migration needs `alembic downgrade` first —
check whether it's actually reversible; V1's additive-only migrations
generally are, via `alembic downgrade -1`), rebuild, restart. If a
migration already ran and can't be cleanly reversed, restore the pre-
upgrade backup instead (`docs/backup-and-restore.md`) rather than fight a
downgrade — restoring is the safer, always-available fallback.

## What never needs a "rollback" step

- Already-deployed applications keep running unaffected by a Control Plane
  restart or upgrade — see the README's "Two paths, kept separate." A
  Control Plane outage during an upgrade doesn't take down anything
  already serving traffic.
- Agent credentials and enrollment survive a Control Plane upgrade (they're
  rows in the same database you backed up/migrated, not separate state).
