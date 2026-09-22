# Healer V1 — Data Model

PostgreSQL is the single source of truth. All access goes through the
repository/service layer in `services/control-plane/app/repositories` and
`app/services` — API route handlers never issue raw SQL or touch `Session`
directly (see `app/repositories/base.py`).

## Conventions

- **Primary keys**: UUID (`uuid4`), generated in Python (`app/db/models/mixins.py:UUIDPrimaryKeyMixin`).
- **Timestamps**: `created_at`/`updated_at` are `timestamptz`, set by the
  database (`server_default=now()`), UTC (`TimestampMixin`).
- **Enums**: explicit Postgres native enums for every status/type field —
  see `app/db/models/enums.py`. Never a free-text status column.
- **Deletion behavior**: child rows `ON DELETE CASCADE` their parent (e.g. an
  application's releases, instances, deployments); rows that reference an
  actor or an optional grouping use `ON DELETE SET NULL` (e.g.
  `deployments.created_by`, `audit_logs.actor_id`) so history survives the
  referenced row being removed.

## Entities

| Table | Purpose |
|---|---|
| `users`, `roles`, `user_roles`, `refresh_sessions` | Administrator accounts, RBAC (seeded: Administrator, Operator, Viewer), login sessions. |
| `servers`, `enrollment_tokens` | Registered Windows/Linux servers and the one-time tokens used to enroll their Agent. |
| `agents`, `agent_connections`, `agent_commands`, `agent_events` | One Agent identity per server; connection history; commands sent to the Agent (idempotency-keyed); events reported back. |
| `applications`, `sources`, `configurations`, `releases`, `instances` | An application, where its code comes from, its config, its releases, and the running instances (server + port) for a release. |
| `deployments`, `deployment_steps`, `deployment_logs` | A deploy of one release with a target instance count; its steps and log lines. |
| `domains`, `upstream_groups`, `upstream_instances` | The hostname an application answers on and which instances sit behind it — feeds the Gateway Manager (Phase 1 scope: reference model only, not yet rendered). |
| `health_checks`, `health_check_results` | Per-application health check configuration and per-instance results. |
| `secret_records` | Encrypted application/global secrets (`encrypted_value` — encryption itself is implemented when secrets management ships). |
| `metrics_snapshots` | Periodic CPU/RAM/disk snapshots per server, pushed by the Agent. |
| `audit_logs` | Administrative action history shown in the dashboard's Audit Log view. |
| `notifications` | In-app notifications, optionally scoped to a user. |

Full column definitions live in the ORM models
(`services/control-plane/app/db/models/`) — that is the source of truth, not
this table.

## Constraints worth knowing about

- `instances`: `UNIQUE (server_id, port)` — a port can't be double-allocated
  on one server (different servers may reuse the same port).
- `domains.hostname`: globally unique.
- `agent_commands.idempotency_key`: globally unique — retried command
  submissions from the Control Plane are safe to resend.
- `health_checks.application_id`: unique — one health check config per
  application in V1.

## State machines

Status transitions for `deployments`, `instances`, and `agent_commands` are
validated centrally in
[`app/domain/state_machines.py`](../services/control-plane/app/domain/state_machines.py)
— e.g. a deployment can't jump from `pending` straight to `succeeded`, and
`rolled_back` is terminal. Repositories (`DeploymentRepository.transition`,
`InstanceRepository.transition`, `AgentCommandRepository.transition`) are the
only supported way to change a status column; they raise `InvalidTransition`
rather than silently allow an illegal jump. See `tests/test_state_transitions.py`.

## Migrations

Alembic, from `services/control-plane`:

```bash
alembic upgrade head        # apply all pending migrations
alembic current              # show the applied revision
alembic history               # list all revisions
```

Revisions:

- `0001_baseline` — empty, establishes migrations as working (Phase 1).
- `0002_core_schema` — creates every table in the entity list above, via
  `alembic revision --autogenerate` against the ORM models.
- `0003_seed_default_roles` — idempotently inserts the three default roles
  (`INSERT ... ON CONFLICT (name) DO NOTHING`), so a clean database has them
  immediately after `alembic upgrade head`.

### Rollback

```bash
alembic downgrade -1     # undo the most recent migration
alembic downgrade 0001   # roll back to a specific revision
alembic downgrade base   # undo everything
```

`0002`'s `downgrade()` drops every table it created **and** the Postgres
native enum types those tables used — Alembic's autogenerate does not add
the enum-type drops on its own (a known limitation with native enums), so
they're added by hand at the end of the migration. Without that, a
downgrade-then-upgrade cycle fails with `type "..." already exists` because
the orphaned enum type is still in the database. Verified locally with a
full `upgrade head` → `downgrade base` → `upgrade head` round trip.

`0003`'s `downgrade()` deletes exactly the three seeded rows by name, so any
additional roles created later are left alone.
