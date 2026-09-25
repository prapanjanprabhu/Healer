# Deploy

Docker Compose stack for local development.

## Clean-server V1 release

Use [`docker-compose.release.yml`](docker-compose.release.yml) for an
installation. Check out the source tag matching `VERSION`, copy `.env.example`
to `.env`, set real secrets and a browser-accessible
`NEXT_PUBLIC_CONTROL_PLANE_URL`, and set `HEALER_VERSION` to the source tag.
Set `GATEWAY_HTTP_PORT=80` and `GATEWAY_HTTPS_PORT=443` when this gateway
owns the public HTTP/HTTPS ports. Then run from the repository root:

```bash
docker compose -f deploy/docker-compose.release.yml --env-file .env build
docker compose -f deploy/docker-compose.release.yml --env-file .env up -d postgres redis
docker compose -f deploy/docker-compose.release.yml --env-file .env run --rm --no-deps control-plane alembic upgrade head
docker compose -f deploy/docker-compose.release.yml --env-file .env up -d
```

The release file builds local images tagged with `HEALER_VERSION`, keeps the
application code inside those images, and starts the central gateway by
default. PostgreSQL and Redis have no public host ports. The local development
Compose file below still bind-mounts source and runs hot reload.

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
