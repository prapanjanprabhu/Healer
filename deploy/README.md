# Deploy

Docker Compose stack for local development.

**Run `docker compose` from the repo root, not from inside this directory** —
see the root [`docker-compose.yml`](../docker-compose.yml) for why: it's what
makes Compose find the real `.env` automatically, without needing
`-f`/`--env-file` flags. Running `docker compose -f docker-compose.yml ...`
from inside `deploy/` (or without `--env-file ../.env`) will silently fall
back to this file's hardcoded defaults instead of your real `.env` values —
most commonly showing up as "password authentication failed for user
healer" even though the database itself has the right password.

## Local dev stack

```bash
cp ../.env.example ../.env   # from repo root: cp .env.example .env
make -C .. up                # or, from the repo root: docker compose up -d --build
```

Services started by default: `postgres`, `redis`, `control-plane`, `worker`,
`dashboard`.

`gateway-manager` is **not** started by default — it only runs under the
`gateway` Compose profile, and only binds to `127.0.0.1` even then. See
[`docs/security-boundaries.md`](../docs/security-boundaries.md) for why.

It exposes its own Nginx listeners too (`GATEWAY_HTTP_PORT`/
`GATEWAY_HTTPS_PORT`, default `8080`/`8443`), plus a read-only bind mount of
`./certs` to `/etc/healer/certs` inside the container — put existing CRT/KEY
files there and reference them by that container-internal path in an
application's `domain.cert_path`/`key_path`. See
[`docs/gateway-routing.md`](../docs/gateway-routing.md) for what it does with
them.

```bash
# from the repo root
docker compose --profile gateway up -d --build gateway-manager
```
