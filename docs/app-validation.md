# Healer V1 — Application Validation (Phase 6)

`POST /applications/{id}/validate` checks a saved [`healer.yaml`](healer-yaml.md)
config and returns a structured list of issues (`error` / `warning` / `info`
severity) — it never deploys anything, runs a migration, starts a process,
or touches Nginx. It also never accepts or runs an arbitrary shell command
from the dashboard: everything below is either a pure Python check against
Control Plane state, or one of the ten fixed structured commands
(`validate_app`) sent to the target server's Agent.

## Where each check actually runs

| Check | Runs in | Why |
|---|---|---|
| Domain hostname uniqueness | Control Plane (`app/domain/app_validation.py`) | Just a DB query against `domains`. |
| Secret references exist | Control Plane | Just a DB query against `secret_records` — never returns a value, see [`docs/data-model.md`](data-model.md). |
| Port range vs. Healer's own instance bookkeeping | Control Plane | Cross-checks `instances.port` for the target server — catches conflicts Healer itself already knows about. |
| Certificate/key pair | Gateway Manager, called by the Control Plane | The restricted Gateway Manager is the only thing that reads certificate files — see [`docs/security-boundaries.md`](security-boundaries.md). |
| Source path / Python executable / requirements file / manage.py / WSGI + settings modules / Healer data-dir writability | **The target server's Agent** | These are facts about that specific machine's filesystem — the Control Plane has no way to know them. |
| Docker availability / Dockerfile / internal port | **The target server's Agent** | Same reasoning, for the Linux adapter. |
| Real OS-level port-range availability | **The target server's Agent** | A port can be occupied by something Healer doesn't know about — only the machine itself can say for sure. |

The Agent-run checks all go through one existing structured command,
`validate_app` (`protocols/v2/command-envelope.schema.json`), described more
fully in [`docs/agent-runtime.md`](agent-runtime.md#restricted-dispatch--no-shell-command-ever).
`POST /applications/{id}/validate` submits it and waits (up to ~20s) for the
Agent's structured result via
`app/services/command_service.submit_command_and_wait` — cross-task
signaling within the single control-plane process, the same constraint
noted for the connection registry in `docs/agent-protocol.md`.

## What "clearly rejected" looks like

Every issue has:

- `field` — a dotted path into the config (`windows.python_executable`,
  `domain.hostname`, `secrets.DB_PASSWORD`, ...) so a UI can point at the
  exact form field.
- `severity` — `error` (the response's top-level `ok` becomes `false`),
  `warning` (surfaced but doesn't block), or `info` (e.g. a computed
  certificate fingerprint or a Python version string).
- `message` — a plain-English reason, never a stack trace.

Example: pointing `python_executable` at a path that doesn't exist on the
target server produces exactly one `error`-severity issue on field
`windows.python_executable` with a message naming the missing path — not a
500, not a generic "invalid config."

## Explicit non-goals (Phase 6)

- No git `ls-remote`/clone to verify a `source.type: git` repo is reachable
  — that happens at actual deploy time (a later phase).
- No `docker pull`/image inspection for `source.type: image` — only that the
  reference string is non-empty.
- No secret value encryption at rest yet (`SecretRecord.encrypted_value` is
  a tracked, documented gap — see `docs/data-model.md`); what's guaranteed
  here is the *API contract* (write-only, existence-only reads).
- No migrations, process starts, or Nginx changes — this phase is entirely
  "is this config plausible," not "make it real."
