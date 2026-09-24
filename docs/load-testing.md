# Expected-peak load testing (Phase 15)

## Tool

`scripts/load_test_erp.sh` — no load-testing framework dependency
(no locust/k6/artillery). Real concurrent HTTP requests via `xargs -P`
(genuine OS-level concurrency) + `curl`, round-robining across every port
an application currently has, the same way Nginx's `least_conn` upstream
distributes real traffic.

```
./scripts/load_test_erp.sh "<space-separated ports>" [total_requests] [concurrency]
```

## What it deliberately does and doesn't measure

It hits each instance's health endpoint directly (`127.0.0.1:<port>/health/`),
**not** through the central Nginx gateway — this measures the deployed
application's own real capacity, independent of gateway/network overhead,
which is what actually matters for "will the application survive peak
load." Testing through the gateway too is a reasonable follow-up (point
the script at the gateway's port with a `Host:` header) but isn't required
to answer the capacity question.

## A real run, and a real finding worth keeping

Executed against 4 real Waitress instances of the Phase 12/13 Django test
app, real Windows Services, on the real machine used throughout this
project's live verification:

```
$ ./scripts/load_test_erp.sh "9900 9901 9902 9903" 2000 50
load test: 2000 requests across (9900 9901 9902 9903), concurrency 50
--- results ---
duration: 34s
requests: 2000
succeeded (200): 2000
failed/non-200: 0
throughput: 58 req/s
```

2000/2000 succeeded at 50 concurrent requests distributed across 4
instances (effectively ~12-13 concurrent per instance) — well within
Waitress's default thread pool (4 threads per instance by default; at
higher sustained concurrency per instance than this, raise
`waitress-serve`'s `--threads` — not currently an exposed `healer.yaml`
setting, worth adding if a real application's expected peak needs more
than the default).

**Database observation, and why the result is "no measurable change" —
correctly:** `pg_stat_activity` connection counts against Healer's own
`healer` database were sampled every ~4 seconds throughout the run and
stayed flat (3 active connections, the same as idle baseline) the entire
time. This is not a null result — it's the load test *confirming* this
project's core architectural claim: real end-user traffic to a deployed
application never touches Healer's own Control Plane database at all (see
the README's "Two paths, kept separate" and `docs/architecture.md`).
Healer's database only sees activity from its own health-check loop
polling instances on its own schedule, decoupled from however much real
traffic those instances are actually serving.

## Re-running this for a specific application before a real event

1. Get its current instance ports:
   `GET /applications/{id}/instances` (or the dashboard's Instance table).
2. `./scripts/load_test_erp.sh "<those ports>" <expected-peak-total> <expected-peak-concurrency>`.
3. Check the Instance table immediately after — every instance should
   still show `healthy: true` with a normal `response_time_ms`, not just
   "the load test script didn't report errors." A health check that
   degrades under load but a plain HTTP 200 that doesn't reflect it is a
   gap the load test alone won't catch.
