# Metrics and logs (Phase 12)

No Prometheus, Loki, or Grafana — see `docs/architecture.md` section 5/7.
Metrics and logs are Healer's own, small, V1-scoped features.

## Metrics

- **Collection**: unchanged from Phase 5 — every connected Agent sends a
  heartbeat (`agent.heartbeat`) on its own interval (default 20s), carrying
  host CPU/RAM/disk percentages. `agent_service.apply_heartbeat` writes one
  `MetricsSnapshot` row per heartbeat. Phase 12 adds nothing new on the
  write path; it adds retention and a read API.
- **Retention**: `metrics_retention.py` runs as a background asyncio task
  (started in `app.main`'s lifespan alongside the health monitor, gated by
  the same `settings.health_monitor_enabled` flag) that deletes
  `MetricsSnapshot` rows older than `settings.metrics_retention_days`
  (default 7) once per hour.
- **Read API**: `GET /servers/{id}/metrics?hours=&limit=` — bounded,
  oldest-first, for the dashboard's summary cards and sparklines
  (`metrics_service.py`).
- **Health latency / process state / agent state**: not re-collected —
  already tracked by earlier phases (`HealthCheckResult.response_time_ms`,
  `Instance.status`, `Agent.status`/`last_seen_at`) and simply surfaced
  by the dashboard next to CPU/RAM/disk.
- **Request/error counters**: Healer does not instrument the deployed
  WSGI application itself (out of scope — it would require injecting
  middleware into arbitrary Django apps). What is genuinely *available* is
  the health-check pass/fail history already recorded per instance
  (`HealthCheckResult`), which the dashboard surfaces as a recent
  success/failure indicator rather than true request-level counters. This
  is a deliberate scope decision, not an oversight.
- **Per-process CPU/RAM**: not collected. The Agent measures the *host*,
  not each supervised child process — adding per-PID accounting would
  need a new cross-referencing layer (PID <-> instance) the instance-host
  supervisor doesn't currently track. Process/container *state* (running/
  restarting/unhealthy) is tracked and shown; per-process resource usage is
  a known V1 gap.

## Logs

- **Log-source registry**: `GET /applications/{id}/log-sources` lists, per
  instance, its `stdout`/`stderr` sources, plus one `deployment` entry
  pointing at the existing `GET /deployments/{id}` log view (unchanged from
  Phase 7/11 — deployment logs already lived in PostgreSQL with no
  retrieval-bound problem, so Phase 12 doesn't touch that path).
- **Bounded retrieval**: a new Agent command, `collect_logs`
  (`agent/internal/dispatcher/collect_logs.go`), reads an instance's
  `<service_name>.out.log`/`.err.log` file with a byte-bounded, line-bounded
  tail (defaults 64KB / 500 lines; hard caps 1MB / 5000 lines — a caller can
  never force a full-file read). Supports an `offset` for forward
  continuation (used by the live tail) or `None` for "tail the end".
  Exposed as `GET /applications/{id}/instances/{instance_id}/logs`.
- **Live tail**: `GET /applications/{id}/instances/{instance_id}/logs/stream`
  — Server-Sent Events. Polls `collect_logs` every ~2s over the existing
  secure Agent WebSocket channel, forwarding only newly-appended,
  already-redacted lines. Bounded to 10 minutes per connection; the
  dashboard reconnects to keep tailing.
- **Redaction**: `log_redaction.py` — pattern-based (password/token/
  API-key/bearer/connection-string shapes) plus exact-match on every
  secret value currently stored for the application
  (`secret_service.get_secret_values`, plaintext today — see that module's
  own tracked-gap docstring). Applied at the Control Plane, once, for
  every log source, rather than duplicated in Go.
- **Search/filter**: by server/application/instance is inherent to the
  endpoint's path; by severity/substring is done client-side in the
  dashboard over the bounded chunk already fetched — there is no
  full-text index over raw log files (that would mean uploading unlimited
  log content into PostgreSQL, which is explicitly out of scope).
- **Local retention/rotation**: instance log files are still append-only
  with no live rotation (unchanged risk from Phase 7), but
  `instancehost.go`'s `openLog` now rotates (renames to `.1`, one backup)
  any file that has grown past 10MB *at each service start* (a fresh
  deploy, a restart, a self-healing recovery) — bounding long-term growth
  without needing a continuously-running rotation daemon. A single very
  long-lived instance that's never restarted can still grow unbounded
  between rotations; a live copytruncate-style rotator is a later phase.
- **Deployment logs**: unchanged — already bounded, already in PostgreSQL,
  already had their own retrieval endpoint. Phase 12 only adds a pointer
  to them from the log-source registry.

## Known V1 simplifications

- No per-application Nginx access/error log separation (Gateway Manager's
  logs stay the shared Debian-stock `/var/log/nginx/{access,error}.log`);
  Phase 12 does not add a log source for them. Per-instance stdout/stderr
  and deployment logs cover the completion test's scope.
- No true request/error-rate metrics from inside the deployed application.
- No live (mid-write) log rotation — only rotation-on-service-start.
