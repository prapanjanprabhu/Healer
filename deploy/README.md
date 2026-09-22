# Deploy

Docker Compose stack for local development, plus the Nginx configuration
templates the Gateway Manager will render in a later phase.

## Local dev stack

```bash
cp ../.env.example ../.env   # from repo root: cp .env.example .env
make -C .. up                # or: docker compose -f docker-compose.yml --env-file ../.env up -d --build
```

Services started by default: `postgres`, `redis`, `control-plane`, `worker`,
`dashboard`.

`gateway-manager` is **not** started by default — it only runs under the
`gateway` Compose profile, and only binds to `127.0.0.1` even then. See
[`docs/security-boundaries.md`](../docs/security-boundaries.md) for why.

```bash
docker compose -f docker-compose.yml --env-file ../.env --profile gateway up -d --build gateway-manager
```

## `templates/nginx`

`upstream.conf.template` is a placeholder for the Nginx server-block template
the Gateway Manager will render from Control Plane state (application slug,
healthy instance ports, certificate/key paths). It is not consumed by any
running code in Phase 1.
