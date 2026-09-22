# Healer Protocols

This directory is the shared contract between the Control Plane and the Agent
(and, where noted, the Gateway Manager). It is versioned independently of any
single service so that agents and control planes can be upgraded without
having to move in lockstep.

## Layout

```
protocols/
  v1/
    envelope.schema.json          common message envelope, all messages use it
    agent-register.schema.json    agent -> control plane, on connect
    agent-heartbeat.schema.json   agent -> control plane, periodic metrics snapshot
    deploy-command.schema.json    control plane -> agent, instructs a deployment
    instance-command.schema.json  control plane -> agent, start/stop/restart
    health-report.schema.json     agent -> control plane, per-instance health
    audit-event.schema.json       control plane internal, audit log entry shape
```

## Versioning rules

- A directory per major version (`v1`, `v2`, ...). Breaking changes to a
  message's required fields or semantics require a new version directory —
  never a silent change to an existing schema file.
- Additive, backward-compatible fields (new optional fields) may be added
  within a version.
- Every message carries `protocol_version` in its envelope so a receiver can
  reject or branch on an unexpected version rather than guess.
- Phase 1 ships the schemas as the agreed contract only; the Control Plane and
  Agent do not yet enforce or fully implement every message type — that lands
  with deployment behavior in a later phase.

## Envelope

Every message — in either direction — is wrapped in the common envelope
defined in [`v1/envelope.schema.json`](v1/envelope.schema.json):

```json
{
  "protocol_version": "1.0",
  "message_id": "b3f2b3f0-3e9b-4c7d-8e8a-5a1e9f6b2b41",
  "type": "agent.heartbeat",
  "timestamp": "2026-01-15T12:00:00Z",
  "payload": { "...": "message-type-specific fields" }
}
```

`type` selects which payload schema applies (e.g. `agent.register`,
`agent.heartbeat`, `control.deploy_command`, `control.instance_command`,
`agent.health_report`).

## Message catalogue (V1 contract)

| `type` | Direction | Schema | Purpose |
|---|---|---|---|
| `agent.register` | agent → control plane | `agent-register.schema.json` | Announce a server and its capabilities when the agent connects. |
| `agent.heartbeat` | agent → control plane | `agent-heartbeat.schema.json` | Periodic CPU/RAM/disk + per-instance status snapshot. |
| `agent.health_report` | agent → control plane | `health-report.schema.json` | Result of a health check performed against one application instance. |
| `control.deploy_command` | control plane → agent | `deploy-command.schema.json` | Deploy a release: source, instance count, ports, adapter type. |
| `control.instance_command` | control plane → agent | `instance-command.schema.json` | Start / stop / restart a specific instance. |

`audit-event.schema.json` is not carried over the wire to the agent; it defines
the shape the Control Plane stores in PostgreSQL for the administrative audit
history and is documented here because it is a shared, versioned contract in
its own right.
