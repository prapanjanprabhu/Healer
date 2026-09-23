# Deploy

Docker Compose stack for local development, plus the Nginx configuration
templates the Gateway Manager will render in a later phase.

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

```bash
# from the repo root
docker compose --profile gateway up -d --build gateway-manager
```

## `templates/nginx`

`upstream.conf.template` is a placeholder for the Nginx server-block template
the Gateway Manager will render from Control Plane state (application slug,
healthy instance ports, certificate/key paths). It is not consumed by any
running code in Phase 1.
