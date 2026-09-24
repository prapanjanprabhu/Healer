# Healer V1 — Security Boundaries

This document exists so that later phases don't accidentally erode the isolation
built into Phase 1.

## 1. The Gateway Manager is restricted by design

`services/gateway-manager` is the only process allowed to render Nginx
configuration and trigger a reload of the one central Nginx installation. It is
kept deliberately small and isolated:

- It is **never** exposed on a public network interface. In `deploy/docker-compose.yml`
  it only runs under the `gateway` profile and binds to a loopback/internal address
  (`GATEWAY_MANAGER_HOST=127.0.0.1` by default).
- It is **never** called directly by the dashboard. Only the Control Plane may call
  it, and only over the internal network, authenticated with a shared secret
  (`GATEWAY_MANAGER_SHARED_SECRET`).
- It has no database access and no agent connections. Its only job is: accept a
  rendering/reload instruction from the Control Plane, validate it, write Nginx
  config, reload Nginx.
- `POST /reload` (Phase 8) renders one application's Nginx server block from
  structured `app_slug`/`domains`/`upstreams` fields only — never raw config
  text or a shell command — validates with `nginx -t`, and restores the
  previous working config on any validation or reload failure. See
  [`docs/gateway-routing.md`](gateway-routing.md).

## 2. Agents are outbound-only

The Go agent that runs on each managed Windows/Linux server initiates an outbound
secure WebSocket connection (`wss://`) to the Control Plane. The Control Plane
never initiates an inbound connection to a managed server. This means:

- Managed servers do not need any inbound firewall rule opened toward them for
  Healer to operate.
- An agent's blast radius if compromised is limited to the server it runs on plus
  whatever the Windows/Linux V1 adapter is authorized to do on that host (start,
  stop, restart application processes/containers) — it is not a general remote
  shell and V1 does not add one.
- Each agent enrolls with a distinct token (`AGENT_ENROLLMENT_TOKEN` placeholder
  in `.env.example`); tokens are per-server, not shared.

## 3. Dashboard has no direct infrastructure access

The dashboard (`apps/dashboard`) only ever calls the Control Plane's HTTP API
(`NEXT_PUBLIC_CONTROL_PLANE_URL`). It has no direct connection to PostgreSQL,
Redis, agents, or the Gateway Manager. This keeps a browser-facing surface from
ever needing infrastructure credentials.

## 4. Worker jobs are not exposed directly

Celery (`services/worker`) only receives jobs enqueued by the Control Plane
through Redis. It is not reachable from the dashboard, from agents, or from the
public internet.

## 5. Certificates

Healer V1 only reads existing CRT/KEY file paths supplied by the administrator
(`DEFAULT_CERT_PATH`, `DEFAULT_KEY_PATH`). It never generates keys, never talks to
an ACME provider, and never uploads private key material through the dashboard.

## 6. Administrator sessions and CSRF

Dashboard sessions use HttpOnly, `SameSite=Lax` cookies for the access and
refresh tokens (never readable by JS, so an XSS bug can't exfiltrate them)
plus a separate, non-HttpOnly CSRF cookie that same-origin JS must echo back
as a header on mutating requests. Full design, rotation, and revocation
behavior: [`docs/auth.md`](auth.md). Passwords, tokens, and secret values are
never written to the audit log or CLI output.

## 6a. The Linux Docker adapter's shape (Phase 13)

Neither this document nor `docs/architecture.md` fixed a security shape for
the Linux adapter before Phase 13 built it, beyond "the Agent drives the
local Docker daemon" — so this is that decision, made explicit:

- The Agent talks to the Docker daemon directly over its Unix socket
  (`/var/run/docker.sock`, or `HEALER_DOCKER_SOCKET` for tests), issuing
  fixed, structured Engine API calls (`agent/internal/dockerengine`) — never
  shelling out to the `docker` CLI, never a command string built from
  Control Plane input. Whoever can reach that socket already has root-
  equivalent control of the host; the Agent is trusted with that on the
  servers it's enrolled on, the same trust level the Windows adapter's
  LocalSystem-installed service already carries.
- Every managed container joins one shared bridge network per host
  (`healer-apps`, created on demand). V1 does not isolate applications from
  each other at the network layer beyond Docker's own per-container
  namespace — no stated requirement for that existed, and adding it (a
  network per application, or per-application firewall rules) is a
  deliberate later change, not something to add incidentally.
- Resource limits (`linux.cpu_limit`, `linux.memory_limit_mb` in
  `healer.yaml`) are optional and administrator-set; omitted means
  unlimited, matching how the Windows adapter also doesn't cap a Waitress
  process's resource usage today.
- Images: either built from a Dockerfile the administrator points at (no
  arbitrary build args or `--privileged`), or pulled from an explicit,
  administrator-supplied reference. V1 does not restrict which registries
  can be pulled from and does not require digest pinning — the same trust
  model as the Windows adapter's `python_executable`/source-folder path,
  which is likewise administrator-supplied and not sandboxed further.
- Containers never run `--privileged` and are never given extra Linux
  capabilities beyond Docker's defaults; nothing in the Agent's container-
  create payload requests either.

## 7. Explicit non-goals (do not add in V1)

- No remote interactive shell to managed servers.
- No Prometheus/Loki/Grafana ingestion endpoints.
- No Kubernetes control loop or API.
- No public exposure of the Gateway Manager or the worker.

Any change to these boundaries should be a deliberate, reviewed spec change —
not an incidental side effect of a feature PR.
