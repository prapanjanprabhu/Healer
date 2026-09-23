"""Synchronous HTTP health checks. Used two ways:

- On-demand, to gate adding a newly-started instance to Nginx during a
  scale-up (see app/services/scale_service.py).
- Continuously, by app/services/health_monitor.py's background loop, which
  polls every already-RUNNING instance at its configured cadence and hands
  a failing one to app/services/self_healing_service.py.

Blocking (uses `time.sleep`/a synchronous HTTP client) — callers run it via
`asyncio.to_thread`, never directly from a request handler.
"""

import time
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from app.db.models.health import HealthCheck, HealthCheckResult


def check_instance_once(
    host: str, port: int, path: str, timeout_seconds: float, expected_status: int | None = None
) -> tuple[bool, str, int | None]:
    """One HTTP GET.

    With no `expected_status` configured (the default, and all of Phase 9's
    behavior): any response at all, even a 4xx, proves the process is up
    and accepting connections — only a failed connection, a timeout, or a
    5xx counts as unhealthy. With `expected_status` set, the status code
    must match exactly.
    """
    url = f"http://{host}:{port}{path}"
    start = time.monotonic()
    try:
        response = httpx.get(url, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        return False, str(exc), None
    elapsed_ms = int((time.monotonic() - start) * 1000)
    healthy = (
        response.status_code == expected_status
        if expected_status is not None
        else response.status_code < 500
    )
    return healthy, f"HTTP {response.status_code}", elapsed_ms


def wait_until_healthy(
    session: Session,
    health_check: HealthCheck,
    instance_id: uuid.UUID,
    *,
    host: str,
    port: int,
) -> bool:
    """Polls at the configured cadence until `healthy_threshold` consecutive
    successes (returns True) or `unhealthy_threshold` consecutive failures
    (returns False) — the same thresholds a continuous poller would use,
    just run once. Every attempt is recorded as a HealthCheckResult so the
    instance table's "health"/"response time" columns have real data from
    the moment an instance starts.
    """
    consecutive_successes = 0
    consecutive_failures = 0
    max_attempts = health_check.healthy_threshold + health_check.unhealthy_threshold
    for _ in range(max_attempts):
        healthy, detail, response_time_ms = check_instance_once(
            host,
            port,
            health_check.path or "/",
            health_check.timeout_seconds,
            health_check.expected_status,
        )
        if healthy:
            consecutive_successes += 1
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            consecutive_successes = 0

        session.add(
            HealthCheckResult(
                health_check_id=health_check.id,
                instance_id=instance_id,
                healthy=healthy,
                detail=detail,
                consecutive_failures=consecutive_failures,
                response_time_ms=response_time_ms,
                checked_at=datetime.now(UTC),
            )
        )
        session.commit()

        if consecutive_successes >= health_check.healthy_threshold:
            return True
        if consecutive_failures >= health_check.unhealthy_threshold:
            return False
        time.sleep(health_check.interval_seconds)
    return False
