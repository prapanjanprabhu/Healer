# The Linux Docker adapter (Phase 13)

The second of Healer's two V1 adapters, parallel to the Windows Django/
Waitress adapter (`docs/app-deployment.md`) — same Deployment/Release/
Instance state machines, same blue-green/rollback flow
(`docs/blue-green-deployment.md`), same scaling and self-healing, same
Nginx gateway integration. What's actually adapter-specific is small: how a
release is materialized (a Docker image instead of a venv) and how an
instance is run (a container instead of a Windows Service).

## What's shared, unchanged, and adapter-agnostic

Confirmed while building this phase, not just assumed:

- `Deployment`/`Release`/`Instance` tables, their state machines, and every
  orchestration function in `deployment_service.py`/`release_service.py`/
  `scale_service.py`/`self_healing_service.py` — all already worked off
  `Instance.port`/`Server.hostname` and generic Agent command results. The
  only adapter-specific code was two payload-builder functions and one
  hardcoded guard in `deployment_service.start_deployment`.
- `gateway_service.py` and the Gateway Manager's Nginx template
  (`app.conf.j2`) — an upstream is just a list of `{host, port}` pairs.
  A Docker container's host-published port plugs in exactly like a Waitress
  instance's bound port; no gateway-manager change was needed.
- `_allocate_instance`'s transactional port allocation — works off
  `Application.port_range_start/end` and `Instance.port` alone, no adapter
  awareness needed.

## What's new

**Payload shape.** `AgentCommandType` stays the same closed ten-verb set —
`deploy_release`/`start_instance`/`stop_instance` are OS-agnostic verbs.
Their payloads now carry an `adapter` discriminator and an optional
`linux: {...}` sibling next to the existing `windows: {...}` shape
(mirroring the pattern `validate_app`'s payload already established in
Phase 6). See `deployment_service._build_deploy_release_payload` /
`_build_start_instance_payload` / `_build_stop_instance_payload`.

**`Release.image_ref`** (migration 0010) is the Docker adapter's sibling to
`release_dir`/`venv_python` — the built (tagged `healer-<slug>:<version>`)
or pulled (immutable reference, used as-is) image this release runs from.
`start_rollback` checks it instead of `release_dir`/`venv_python` when the
application's adapter is `linux-docker`.

**Image references are immutable.** An `image` source must use
`repository@sha256:<64 hex digits>`; mutable tags are rejected by both the
Control Plane schema and the Agent. Docker pulls the digest without adding a
`latest` tag.

**Secrets become environment variables.** The Windows adapter never
injected secrets into the process directly (Django reads them from its own
settings module). A container's normal configuration surface *is* its
environment, so `_build_start_instance_payload` merges the application's
literal `linux.env` config with every currently-stored secret value
(`secret_service.get_secret_dict`) into the container's `Env` at start time
— the only point where a secret's raw value leaves the Control Plane.

**The Go Agent's Docker Engine API client** (`agent/internal/dockerengine`)
talks to the local Docker daemon over its Unix socket with a real
`net/http.Client` (a Unix-socket `Transport`), continuing the house style
`validate_app.go`'s `dockerAvailableCheck` established for its read-only
probe. Every operation is a fixed, structured call built from validated Go
values — build (tars the source directory, excluding the same
version-control/cache junk the Windows snapshot step already excludes),
pull, create/start/stop/remove a container, inspect its state, and a
bounded recent-logs read (used for start failure diagnostics, not exposed
through Phase 12's log viewer — see "Known simplifications" below).
`HEALER_DOCKER_SOCKET` overrides the socket path for tests.

**Dispatcher handlers** (`deploy_release.go`, `start_instance.go`,
`stop_instance.go`) now branch on the payload's `adapter` field:
`deployLinuxRelease` builds/pulls and reports `image_ref`;
`startLinuxInstance` ensures the shared `healer-apps` bridge network exists,
then creates and starts a container (converging: any existing container
under the same name is removed first, mirroring `start_instance`'s
Windows-Service-install convergence), waiting for it to reach a genuine
Running state — a container that exits immediately (bad entrypoint, missing
required env var) is reported as a failed step with its recent logs
attached, not a false "started successfully"; `stopLinuxInstance` stops and
removes the container, tolerating "already gone" as success.

**`inspect_host`** reports Docker daemon reachability and version on Linux
hosts (`docker_available`/`docker_version`) — net-new; nothing reported this
before.

**Retention cleanup** uses a constrained `deploy_release` operation for
Dockerfile-built `healer-<slug>:<version>` tags only. The Agent reconstructs
the tag from validated slug and version fields, and Docker refuses removal
while a container still uses the image. Failed cleanup leaves the release
record in place for a later retry. Pulled digest references are shared
cache entries and are left on the host.

## Known simplifications

- No per-application network isolation — every container joins one shared
  `healer-apps` bridge network. See `docs/security-boundaries.md` §6a.
- Container stdout/stderr is available through the log-source registry and
  live-tail API. The Agent asks Docker for one stream at a time and caps the
  response to 1 MiB / 5000 lines. Its offset tracks a bounded recent
  snapshot; very high-volume output that rolls past that window between
  polls can be missed.
- No live (mid-write) resource-limit adjustment — `cpu_limit`/
  `memory_limit_mb` are applied at container creation only, same as the
  Windows adapter has no live resource controls either.
- Image builds always pass `rm=1` (remove intermediate containers) and
  never accept extra build args from the application config — only the
  Dockerfile at the given source location is honored.

## Testing and verification

Automated: `agent/internal/dockerengine`'s tests run a fake Docker Engine
API on a real Unix socket (not mocked HTTP — an actual `net.Listen("unix",
...)` server) covering ping/version/network/build/pull/create/start/stop/
remove/inspect/logs, including the frame-demultiplexing format Docker uses
for non-TTY container logs. `agent/internal/dispatcher`'s
`deploy_release_docker_test.go`/`start_instance_docker_test.go`/
`stop_instance_docker_test.go` exercise the handlers the same way. A
separate, explicitly-skip-gated integration test
(`adapter_integration_test.go`) runs the full
deploy→start→inspect→stop→remove sequence against a genuinely reachable
Docker daemon when one is available. `services/control-plane`'s
`test_linux_docker_adapter.py` covers the Control Plane's own payload
branching, secret-to-env injection, and rollback's image_ref check, mocking
`command_service.submit_command_and_wait` the same way the blue-green and
self-healing test suites already do.

Live verification: a real Go Agent (cross-compiled for Linux) ran inside a
docker-outside-of-docker container with the host's real Docker socket
mounted in, enrolled against the real Control Plane over a real WebSocket.
Through the actual dashboard-facing API (never a test harness shortcut): a
sample containerized app (`agent/testdata/sample-docker-app` — a
dependency-free Python `http.server`) was deployed (a real image build),
scaled from 1 to 3 real running containers, confirmed genuinely healthy by
the real health-check loop, blue-green-switched to a second release (3 new
containers, then the old 3 drained/stopped/removed), rolled back to the
original release without rebuilding, and served real HTTPS traffic through
the actual Gateway-Manager-owned Nginx instance end to end.
