# Healer V1 — Server Registration and Agent Protocol

## Flow

```
1. Administrator: POST /servers                          → registers a Server row (status=pending)
2. Administrator: POST /servers/{id}/enrollment-tokens    → single-use token, shown once, TTL 60min default
3. Agent:         POST /agents/enroll {token}             → consumes the token, returns a long-lived credential (shown once)
4. Agent:         connects wss://.../ws/agent
                   Authorization: Bearer <credential>      → authenticates the connection, not the enrollment token
5. Agent:         sends agent.hello                        → capability report (os/arch/adapters/version)
6. Agent:         sends agent.heartbeat every ~15-30s       → keeps it "online"; also a metrics snapshot
7. Control Plane: sends control.command as needed
8. Agent:         sends agent.command_event                → acknowledged → running → succeeded | failed | timed_out
```

Steps 1-3 are plain REST. Steps 4-8 happen over the one persistent
WebSocket. See [`protocols/README.md`](../protocols/README.md) for the exact
message schemas (v2).

## Why enrollment tokens and the connection credential are different things

The enrollment token is **single-use** and **short-lived** (default 60
minutes) — exactly what you want for something an administrator copies into
an install script and a server uses exactly once. The connection credential
is **long-lived** and **reusable** — exactly what you want for a service
that reconnects on every reboot or network blip without needing a human to
re-issue anything. Conflating them would force a choice between "safe to
paste into a script" and "safe to use for the next two years," so Healer
uses two: the token exists only to bootstrap the credential.

Both are opaque random tokens; only their SHA-256 hash is ever stored
(`app/core/security.hash_token`) — see `servers.enrollment_tokens.token_hash`
and `agents.credential_hash` in [`docs/data-model.md`](data-model.md).
Re-enrolling a server that already has an Agent rotates its credential,
invalidating the old one.

## Structured commands only

Every command sent to an Agent is one of exactly ten types
(`app/db/models/enums.py:AgentCommandType`): `inspect_host`, `validate_app`,
`deploy_release`, `start_instance`, `stop_instance`, `restart_instance`,
`inspect_instance`, `collect_logs`, `collect_metrics`, `update_proxy`.
`CommandSubmitRequest.type` is typed as this enum, so anything else is a 422
validation error before it ever reaches the database — **there is no
shell/free-form command message anywhere in this protocol**, by
construction, not by convention.

Each command type requires a specific human permission to submit
(`app/domain/command_permissions.py`):

| Command | Permission |
|---|---|
| `inspect_host`, `validate_app`, `inspect_instance`, `collect_logs`, `collect_metrics` | `view` |
| `deploy_release`, `update_proxy` | `deploy` |
| `start_instance` | `scale` |
| `stop_instance` | `stop` |
| `restart_instance` | `restart` |

## Idempotency, delivery, and timeouts

- **Idempotency**: `POST /agents/{id}/commands` takes an `idempotency_key`
  (auto-generated if omitted). Resubmitting the same key returns the
  original command — enforced both defensively (a lookup first) and by a
  unique DB constraint (`uq_agent_commands_idempotency_key`).
- **Offline delivery**: if the agent isn't connected when a command is
  submitted, it's created as `pending` and delivered the moment the agent
  (re)connects (`command_service.deliver_pending_commands`, called from the
  WebSocket route right after accepting a connection). This is what makes
  "reconnect" mean something more than the status flipping back to online.
- **Timeout**: every command has an `expires_at` (default 120s from
  submission). `expire_overdue_commands` sweeps overdue commands lazily —
  called from the command list/detail endpoints rather than on a schedule
  (no Celery beat is wired up yet, see Phase 1). A command that expired
  before ever being sent becomes `expired`; one that was sent but never
  finished becomes `timed_out`.
- **Full event history**: `agent_command_events` keeps every
  acknowledged/running/succeeded/failed/timed_out event an agent ever
  reported for a command — `AgentCommand.status`/`.result`/`.error` are the
  current state, the events table is the audit trail behind it.

## Online / offline

`app/domain/agent_status.py:is_online` requires **both** `status ==
CONNECTED` **and** a heartbeat within the last 45 seconds
(`OFFLINE_AFTER_SECONDS`). Relying on `status` alone would report an agent
online forever if its process died without a clean WebSocket close (killed
process, network drop) — the heartbeat recency check catches that case
without needing a background sweep job.

## Fake Agent simulator

- `tests/support/fake_agent.py` — drives a real `/ws/agent` connection
  in-process (Starlette's WebSocket test session, no real network); used by
  `tests/test_agent_protocol.py`.
- `scripts/fake_agent.py` — the same protocol over a **real** network
  WebSocket, for manual testing against a running Control Plane:

  ```bash
  python scripts/fake_agent.py enroll --control-plane http://localhost:8000 --token <token>
  python scripts/fake_agent.py run --control-plane ws://localhost:8000/ws/agent --credential <credential>
  ```

  `run` auto-completes any command it receives with a trivial
  `{"ok": true, ...}` result — there's no real adapter logic behind it
  (that's Phase 5+), it only proves the protocol end to end.

## Dashboard

- `/servers` — list, with an online/offline badge per server.
- `/servers/new` — register a server.
- `/servers/[id]` — connection status (online/offline, agent version, last
  heartbeat) and enrollment token management: issue a new token (shown
  once, with the exact `scripts/fake_agent.py`-style command to run), see
  outstanding tokens, revoke one before it's used.
