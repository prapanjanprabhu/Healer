# Healer Protocols

This directory is the shared contract between the Control Plane and the Agent
(and, where noted, the Gateway Manager). It is versioned independently of any
single service so that agents and control planes can be upgraded without
having to move in lockstep.

## Versions

- **v1** — the Phase 1 contract-only draft. Never implemented against a real
  connection; kept for history. It assumed enrollment happened *over* the
  agent's WebSocket (`agent.register`, carrying the enrollment token) and
  had separate `deploy_command`/`instance_command` payload shapes.
- **v2** — what Phase 4 actually implements. Enrollment is a one-time REST
  call (`POST /agents/enroll`) that happens *before* the WebSocket ever
  opens and returns a long-lived credential; the socket itself carries only
  `agent.hello` (capability report), `agent.heartbeat`, `control.command`
  (one generic envelope for every structured command type), and
  `agent.command_event`. This is a breaking change to the message set, which
  is exactly why it's a new version directory rather than an edit to v1 —
  see "Versioning rules" below.

`protocols/v1/audit-event.schema.json` is unchanged and still current — it
describes a Postgres row shape, not a wire message, so it isn't duplicated
under v2.

## Layout (v2)

```
protocols/v2/
  envelope.schema.json          common message envelope, all messages use it
  agent-hello.schema.json       agent -> control plane, sent once on connect
  agent-heartbeat.schema.json   agent -> control plane, periodic metrics snapshot
  command-envelope.schema.json  control plane -> agent, one structured command
  command-event.schema.json     agent -> control plane, command progress/result
```

## Versioning rules

- A directory per major version (`v1`, `v2`, ...). Breaking changes to a
  message's required fields or semantics require a new version directory —
  never a silent change to an existing schema file.
- Additive, backward-compatible fields (new optional fields) may be added
  within a version.
- Every message carries `protocol_version` in its envelope so a receiver can
  reject or branch on an unexpected version rather than guess.

## Envelope

Every message — in either direction — is wrapped in the common envelope
defined in [`v2/envelope.schema.json`](v2/envelope.schema.json):

```json
{
  "protocol_version": "1.0",
  "message_id": "b3f2b3f0-3e9b-4c7d-8e8a-5a1e9f6b2b41",
  "type": "agent.heartbeat",
  "timestamp": "2026-01-15T12:00:00Z",
  "payload": { "...": "message-type-specific fields" }
}
```

`type` selects which payload schema applies.

## Message catalogue (v2, implemented)

| `type` | Direction | Schema | Purpose |
|---|---|---|---|
| `agent.hello` | agent → control plane | `agent-hello.schema.json` | Capability report, sent once right after connecting. |
| `agent.heartbeat` | agent → control plane | `agent-heartbeat.schema.json` | Periodic CPU/RAM/disk + per-instance status; also what proves the connection is alive. |
| `control.command` | control plane → agent | `command-envelope.schema.json` | One structured command — `type` is one of the ten closed `AgentCommandType` values. No shell/free-form command exists anywhere in this protocol. |
| `agent.command_event` | agent → control plane | `command-event.schema.json` | Progress/result of a command: acknowledged, running, then succeeded/failed/timed_out. |

Enrollment (`POST /agents/enroll`) and command submission
(`POST /agents/{id}/commands`) are plain REST, not part of the WebSocket
message set — see [`docs/agent-protocol.md`](../docs/agent-protocol.md).
