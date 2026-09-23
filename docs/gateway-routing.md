# Healer V1 — Gateway Routing (Phase 8)

Connects a public domain to an application's currently-healthy instance(s)
through the one central Nginx installation the Gateway Manager exclusively
manages. See [`docs/security-boundaries.md`](security-boundaries.md) for why
that service is restricted the way it is.

## Trigger points

- **Automatic:** after a deploy's `start_instance` step succeeds
  (`app/services/deployment_service.py:_sync_gateway_step`), if the
  application has a `domain` configured. Recorded as its own `gateway_sync`
  `DeploymentStep`/`DeploymentLog` — it can never flip an already-succeeded
  Deployment back to FAILED, since the instance is genuinely running
  regardless of whether routing could be updated.
- **Manual:** `POST /applications/{id}/gateway/sync` — re-syncs routing from
  current Domain/Instance state without running a new deployment (e.g. after
  editing domain/certificate config, or to retry a sync that failed).

## What the Control Plane sends

The Gateway Manager has no database access by design, so
`app/services/gateway_service.py:_build_reload_payload` gathers everything
needed and posts one structured JSON payload to `POST /reload`:

```json
{
  "app_slug": "rit-academic-erp",
  "domains": [{"hostname": "...", "cert_path": "...", "key_path": "..."}],
  "upstreams": [{"host": "...", "port": 9034}]
}
```

- `domains`: every `Domain` row for the application that has both a
  `cert_path` and a `key_path` set (an incomplete pair is never sent).
- `upstreams`: one entry per `Instance` currently `RUNNING`, using that
  instance's `Server.hostname` as the address — the same operator-supplied
  value used everywhere else, not something auto-detected. In a single-box
  dev setup where Nginx runs in Docker and the instance runs directly on the
  Windows host, that value needs to be something reachable from inside the
  container (e.g. `host.docker.internal`), not `127.0.0.1`.
- Never Nginx config text, never a shell command — only these three
  structured fields, plus the shared secret in the `X-Gateway-Secret` header.

## What the Gateway Manager does with it

`services/gateway-manager/app/services/nginx_manager.py` is the only code
that ever writes into the managed directory
(`/etc/nginx/conf.d/healer/<app_slug>.conf`) or invokes the `nginx` binary,
and only with fixed argument lists (`nginx -t`, `nginx -s reload` — never a
shell string):

1. Render the application's server block from a fixed Jinja2 template
   (`app/templates/app.conf.j2`) — one `upstream` block (`least_conn`,
   `keepalive 32`) plus an HTTP→HTTPS redirect and an HTTPS server block per
   domain, with standard reverse-proxy headers
   (`X-Real-IP`/`X-Forwarded-For`/`X-Forwarded-Proto`, `Host`, HTTP/1.1
   keepalive). No domains or no healthy upstreams renders nothing — the
   application is taken out of routing rather than emitting a broken (e.g.
   empty) upstream block.
2. Write it to a temp file in the same directory and `os.replace` it into
   place (atomic at the filesystem level).
3. Run `nginx -t` against the whole config (every application's managed file
   together, not just this one).
4. If that fails, restore exactly the bytes that were on disk before this
   call (or remove the file, if none existed) and return `ok: false` with
   nginx's own error text — never touching any other application's file, and
   never calling `nginx -s reload`.
5. If it passes, run `nginx -s reload`. If *that* fails, restore the
   previous state the same way.

This is the mechanism proven by
`services/gateway-manager/tests/test_nginx_manager.py` — including a test
that runs the real `nginx` binary (skipped where one isn't present) and
several that simulate `nginx -t`/`-s reload` failure to prove a bad
generated config never replaces a working one.

## Known simplifications (V1)

- One Nginx installation, colocated in the Gateway Manager's own container —
  no separate Nginx service/container, no multi-node gateway.
- "Healthy" means "Control Plane currently believes this Instance is
  RUNNING" — there is no independent health-check-driven removal yet (that's
  a later phase); a crashed instance stays in the upstream until the next
  sync.
- Static files are not served by Nginx directly (no `location /static/`
  alias to shared storage) — Waitress/Django serves the app itself, so
  `/static/...` 404s through the gateway even though `collectstatic` ran.
- No zero-downtime activation across multiple instances — `UpstreamGroup`/
  `UpstreamInstance` bookkeeping tables exist in the schema but aren't
  populated; upstream membership is computed directly from `Instance` rows
  at sync time, since V1 only ever deploys one instance per application.
