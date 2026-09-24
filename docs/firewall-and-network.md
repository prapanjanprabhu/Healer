# Firewall and network checklist

Healer's traffic flows are deliberately asymmetric — see
`docs/security-boundaries.md` §2 and the README's "Two paths, kept
separate." This checklist follows directly from that shape; nothing here
is a new rule, just what it implies for firewall configuration.

## Inbound to the Healer server (where control-plane/dashboard/gateway-manager run)

| Port | From | Purpose |
|---|---|---|
| 443 (or your `GATEWAY_HTTPS_PORT`) | The public internet / your users | The one central Nginx gateway — real application traffic. |
| 80 (or `GATEWAY_HTTP_PORT`) | The public internet | Only if you serve plain HTTP (e.g. to redirect to HTTPS) — optional. |
| 8000 (Control Plane) | Every managed server's outbound Agent connection, and administrators' browsers | The Agent WebSocket (`/ws/agent`) and the dashboard's API calls both land here. Put this behind your own TLS termination in any real deployment (`wss://`, not `ws://`). |
| 3000 (dashboard) | Administrators' browsers | The dashboard UI. Can be co-located behind the same reverse proxy as 8000, or kept separate — V1 doesn't require either. |

**Never expose**: 8100 (Gateway Manager) or 5432/6379 (Postgres/Redis) to
anything outside the Docker network these services already run on. The
Gateway Manager's own compose binding defaults to `127.0.0.1` specifically
so an operator can't accidentally widen it without noticing — see
`deploy/docker-compose.yml`.

## Outbound from every managed server (Windows or Linux, wherever the Agent runs)

| Destination | Purpose |
|---|---|
| The Control Plane's WebSocket port (8000 by default) | The Agent's one outbound connection — enrollment, heartbeat, commands, metrics. **No inbound rule is ever needed on a managed server** — this is the whole point of the outbound-only design (`docs/security-boundaries.md` §2). |
| Whatever registries/package indexes a deployed application's build step needs | `pip install` (Windows adapter) reaches PyPI (or your internal mirror); `docker build`/`docker pull` (Linux adapter) reaches your container registry. Neither goes through the Control Plane — the Agent does this directly on the managed server. |

## Inside the Docker network (`healer-net`) — no firewall configuration needed, just awareness

Control Plane <-> Postgres, Control Plane <-> Redis, Worker <-> Redis,
Control Plane <-> Gateway Manager (authenticated with
`GATEWAY_MANAGER_SHARED_SECRET`) all happen over the compose-internal
network and are never reachable from outside the Docker host at all unless
you've explicitly published those ports (the default compose file doesn't).

## A note on the Gateway Manager's own listeners

The Gateway Manager owns the actual public-facing Nginx (its container
publishes the *application* traffic ports — 80/443, or your configured
`GATEWAY_HTTP_PORT`/`GATEWAY_HTTPS_PORT` — to the host) while its own
management API (port 8100) stays loopback-bound. Don't confuse the two:
opening 8100 to the internet would let anyone push arbitrary Nginx config
through it; it's guarded by a shared secret specifically because it's
meant to be reachable *only* from the Control Plane's container.

## Quick verification after standing up a new Healer server

```bash
# From a managed server, confirm it can reach the Control Plane (should
# get an HTTP response, even a 404/405 — that means the port is open):
curl -v http://<control-plane-host>:8000/health

# From outside, confirm the Gateway Manager's management port is NOT reachable:
curl -v http://<healer-server-host>:8100/health   # should time out / connection refused

# From outside, confirm the actual gateway IS reachable for a configured domain:
curl -vk https://<your-app-domain>/
```
