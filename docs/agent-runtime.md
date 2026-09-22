# Healer V1 — Agent Runtime (Phase 5)

This is the real cross-platform Go Agent — see
[`docs/agent-protocol.md`](agent-protocol.md) for the wire contract it
speaks and [`agent/README.md`](../agent/README.md) for the CLI.

## Data directory

| OS | Path |
|---|---|
| Windows | `C:\ProgramData\Healer` |
| Linux | `/var/lib/healer` |

Contains `config.json` (control plane URLs, heartbeat interval),
`credential.json` (the long-lived connection credential — 0600 on Unix;
on Windows, access control comes from `ProgramData` itself being
Administrator/SYSTEM-writable by default), `journal.log` (append-only
command execution record), and `logs/agent.log` (structured JSON logs).

## Reconnect and backoff

`internal/transport.Client.Run` dials, and on any disconnect — server
restart, network blip, anything — reconnects with exponential backoff
(1s base, 30s cap, jittered so many agents don't retry in lockstep after a
shared outage). Backoff resets to the base delay on every successful dial,
so a brief blip doesn't leave a later reconnect waiting longer than
necessary. This loop is the Agent's entire connection lifetime; the only
way out is a cancelled context (a clean shutdown request).

## Heartbeat and capability reporting

Right after connecting, the Agent sends `agent.hello` once (version, OS,
arch, adapters). Then, every `heartbeat_interval_seconds` (default 20), it
samples CPU/RAM/disk (`internal/metrics`, via gopsutil) and sends
`agent.heartbeat`. Both are also what the Control Plane's online/offline
calculation depends on — see `docs/agent-protocol.md`.

## The command journal — why duplicates can't re-execute

`internal/journal.Journal` is an append-only, fsync'd local log of every
command's status transitions (`received` → `running` → `completed`),
replayed into memory on open. Before executing anything,
`internal/core.Agent.handleMessage` checks `journal.IsCompleted(commandID)`
— if true, the command is ignored rather than re-run. This holds even
across an Agent restart: the journal is what "durable" means here. See
`tests/journal_test.go`'s `TestJournalRecoversStateAfterReopen`.

## Restricted dispatch — no shell command, ever

`internal/dispatcher.Dispatcher` only recognizes the ten structured command
types in `protocols/v2/command-envelope.schema.json`
(`protocol.KnownCommandTypes`). Phase 5 registers a handler for exactly one
of them, `inspect_host` — a safe, read-only report of basic host facts. The
other nine are recognized (part of the closed protocol) but rejected with
`ErrNotImplemented` rather than silently doing nothing or falling through
to something dangerous; an entirely unrecognized type gets
`ErrUnknownCommand`. `dispatcher.Dispatcher.Register` panics if asked to
register a handler for a type outside the known set — a deploy handler
added carelessly in a later phase can't accidentally introduce a new,
unreviewed command type by typo.

## Timeouts and cancellation

Every command carries an `expires_at` (see the protocol doc). `core.Agent.execute`
wraps the dispatcher call in `context.WithDeadline(ctx, *cmd.ExpiresAt)`; a
handler that respects its context (as all handlers must) returns
`context.DeadlineExceeded`, which `execute` reports as a `timed_out` event
rather than `failed` — a caller can tell "it didn't finish in time" apart
from "it errored."

## Clean shutdown

`cmd/healer-agent run` builds its context with
`signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)`.
Cancelling that context is the one signal every layer understands: the
transport client's blocked `ReadJSON` is unblocked by closing the
connection from a goroutine watching `ctx.Done()`, `Client.Run` returns
`ctx.Err()`, and `healer-agent` logs "shut down cleanly" and exits 0. The
same context is what a Windows Service stop request or `systemctl stop`
ultimately cancels — see below.

## OS service integration

Both platforms expose the same `internal/service` API
(`Install`/`Uninstall`/`Start`/`Stop`/`RunAsService`), with the actual
mechanism entirely different per OS:

- **Windows** (`service_windows.go`): `golang.org/x/sys/windows/svc` +
  `svc/mgr`. `healer-agent service install` calls `mgr.CreateService`;
  `healer-agent run`, when it detects it was launched by the Service
  Control Manager (`svc.IsWindowsService()`), calls `svc.Run` with a
  handler that starts the Agent, reports `Running` to the SCM, and turns a
  `Stop`/`Shutdown` control request into cancelling the Agent's context.
- **Linux** (`service_linux.go`): a systemd unit
  (`agent/systemd/healer-agent.service`, `Type=simple`) that just runs
  `healer-agent run` directly — systemd tracks the process itself and
  sends `SIGTERM` on stop, which the signal-handling described above
  already covers. `healer-agent service install/uninstall/start/stop` shell
  out to `systemctl`; `agent/systemd/install.sh`/`uninstall.sh` are the
  standalone equivalent for bootstrapping a server without the binary
  already having run once.

Installing a Windows Service requires an elevated (Administrator) process —
`mgr.Connect()` fails with "Access is denied" otherwise, by design (Windows
requires elevation to touch the Service Control Manager, regardless of
account).

## Verified

This phase was verified against the actual running Control Plane, not only
`go test`:

- **Windows**: built natively on a real Windows 11 machine, enrolled for
  real, ran interactively (connected, heartbeated real CPU/RAM/disk,
  executed a real `inspect_host` command returning this machine's actual
  hostname/CPU count/uptime), then installed as a real Windows Service via
  `mgr.CreateService`, started it (`Get-Service` showed `Running`),
  confirmed it reconnected under the SCM (`"as_service":true` in the log),
  stopped it, and uninstalled it.
- **Linux**: built for `linux/amd64`, run inside a real Alpine container
  against the same live Control Plane over the actual Docker host network
  — enrolled, connected, heartbeated, executed a real `inspect_host`
  command (returning the container's actual hostname/kernel version), and
  shut down cleanly on `SIGTERM` (systemd's stop signal).
- All test-created servers/agents/commands/audit entries were deleted from
  the dev database afterward.

`go build`/`go vet`/`go test` all pass for both `GOOS=windows` and
`GOOS=linux`, and `gofmt -l` reports no formatting issues.
