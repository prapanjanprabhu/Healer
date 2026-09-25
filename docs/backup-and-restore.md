# Backup and restore (Phase 15)

Healer's entire durable state lives in one PostgreSQL database (`healer` by
default) — the Control Plane, worker, and gateway-manager hold no other
persistent state of their own. Backing up that one database is backing up
the whole system's configuration and history (servers, applications,
releases, deployments, instances, users/roles, audit log, secrets — still
as ciphertext, see `docs/security-boundaries.md` §6a and
`app/core/secret_crypto.py`). Deployed application code/venvs/images and
local log files live on each managed server, outside Healer's own backup
scope — back those up (or keep them redeployable from source) separately.

## Backup

```
make backup
```

Runs `pg_dump` inside the running `postgres` container in the custom
(`-F c`) format — compressed, and restorable selectively or in parallel —
and copies the result to `backups/<timestamp>.dump` on the host.
`backups/` is gitignored; treat these files the same way you'd treat any
other credential-bearing artifact (they contain every stored secret's
ciphertext, user password hashes, and JWT signing material is NOT included
— that's `CONTROL_PLANE_SECRET_KEY`, an env var, not database state).

Schedule this however your environment already schedules cron-like jobs;
V1 does not ship its own backup scheduler.

## Restore rehearsal (genuinely run, not just documented)

`make restore FILE=backups/<timestamp>.dump` never restores over the live
`healer` database — it creates a new `healer_restore_<timestamp>` database
and restores into that, so a rehearsal is always safe to run against a live
system. This was actually executed once while writing this doc, against a
real backup of the real development database:

```
$ make backup
backup written to backups/healer_backup_20260924193806.dump

$ make restore FILE=backups/healer_backup_20260924193806.dump
restored into database healer_restore_20260924193817 — inspect it, then drop it when done:
  docker compose exec postgres dropdb -U healer healer_restore_20260924193817
```

Row counts and actual row content (every user's `id`/`email`) were compared
between the live `healer` database and the restored copy and matched
exactly — `servers: 3`, `applications: 1`, `users: 3`, `audit_logs: 194`,
byte-for-byte identical UUIDs and emails.

That comparison is now also automated — `make backup-restore-test`
(`scripts/backup_restore_rehearsal.sh`) runs `make backup`, restores into a
scratch database, asserts every table's row count matches between the live
and restored databases, then drops the scratch database and deletes the
dump it made. Run it against any live `make up` stack; it exits non-zero on
any mismatch, so it's safe to wire into a periodic check.

To actually recover a lost/corrupted database (not a rehearsal):

1. Stop anything writing to it: `docker compose stop control-plane worker`.
2. Restore into a scratch database as `make restore` does, confirm it looks
   right.
3. Rename databases (or point `DATABASE_URL`/the `POSTGRES_DB` env var at
   the restored one — either works; renaming keeps every other setting
   unchanged):
   ```
   docker compose exec postgres psql -U healer -d postgres -c \
     "ALTER DATABASE healer RENAME TO healer_broken; ALTER DATABASE healer_restore_<timestamp> RENAME TO healer;"
   ```
4. `docker compose up -d control-plane worker` — migrations are already at
   whatever revision the backup was taken at; run `make migrate` only if
   the restored backup predates a schema change you've since deployed.
5. Confirm the real Windows/Linux Agents reconnect (they always retry with
   backoff — see `docs/agent-runtime.md`) and that `GET /health` and a
   login succeed before considering the incident resolved.

## What's out of scope for V1

- No point-in-time recovery (WAL archiving) — only whole-database
  snapshot/restore via `pg_dump`/`pg_restore`.
- No automatic backup scheduling or off-host upload — `make backup` writes
  to the local `backups/` directory only; copying it somewhere durable
  (another host, object storage) is an operational step outside Healer's
  own scope, the same way TLS certificate provisioning is (see
  `docs/security-boundaries.md` §5).
