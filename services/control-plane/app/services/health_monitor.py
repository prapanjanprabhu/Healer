"""The continuous health-check loop — see docs/self-healing.md.

Runs as a single asyncio background task inside the Control Plane process
(started from app.main's lifespan, gated by settings.health_monitor_enabled
so it never runs during tests). It must live in this same process: healing
sends Agent commands and waits for their result via command_service's
asyncio.Event coordination, which — like every other command in this V1 —
only works within the process holding the WebSocket connection.

Each tick:
- HTTP-polls every RUNNING instance whose configured `interval_seconds` has
  elapsed since its last result, recording a HealthCheckResult every time.
  A run of `unhealthy_threshold` consecutive failures hands the instance to
  self_healing_service.
- Also re-visits every already-UNHEALTHY instance (no HTTP poll needed —
  it's already known down) so a healing attempt deferred by
  `restart_cooldown_seconds` gets retried once that cooldown has passed,
  rather than being stuck forever once it's no longer RUNNING and so
  invisible to the poll above.

Uses its own DB session per tick (SessionLocal, not a request-scoped
session) since this loop outlives any single request — the same pattern
Celery workers use.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.application import Application, Instance
from app.db.models.enums import InstanceStatus
from app.db.models.health import HealthCheck, HealthCheckResult
from app.db.models.server import Server
from app.db.session import SessionLocal
from app.services import health_check_service, lock_service, self_healing_service
from app.services.lock_service import OperationLockHeldError

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5.0


async def run_forever() -> None:
    while True:
        try:
            await tick()
        except Exception:
            logger.exception("health monitor tick failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def tick() -> None:
    session = SessionLocal()
    try:
        health_checks = {hc.application_id: hc for hc in session.scalars(select(HealthCheck)).all()}
        for application_id, health_check in health_checks.items():
            application = session.get(Application, application_id)
            if application is None or application.server_id is None:
                continue
            server = session.get(Server, application.server_id)
            if server is None:
                continue

            running = session.scalars(
                select(Instance).where(
                    Instance.application_id == application.id,
                    Instance.status == InstanceStatus.RUNNING,
                )
            ).all()
            for instance in running:
                await _poll_and_maybe_heal(session, application, instance, health_check, server)

            unhealthy = session.scalars(
                select(Instance).where(
                    Instance.application_id == application.id,
                    Instance.status == InstanceStatus.UNHEALTHY,
                )
            ).all()
            for instance in unhealthy:
                await _heal(session, application, instance, health_check)
    finally:
        session.close()


async def _poll_and_maybe_heal(
    session: Session,
    application: Application,
    instance: Instance,
    health_check: HealthCheck,
    server: Server,
) -> None:
    last_result = session.scalars(
        select(HealthCheckResult)
        .where(HealthCheckResult.instance_id == instance.id)
        .order_by(HealthCheckResult.checked_at.desc())
    ).first()
    now = datetime.now(UTC)
    if last_result is not None:
        due_at = last_result.checked_at + timedelta(seconds=health_check.interval_seconds)
        if now < due_at:
            return

    healthy, detail, response_time_ms = await asyncio.to_thread(
        health_check_service.check_instance_once,
        server.hostname,
        instance.port,
        health_check.path or "/",
        health_check.timeout_seconds,
        health_check.expected_status,
    )
    consecutive_failures = 0
    if not healthy:
        consecutive_failures = (
            (last_result.consecutive_failures + 1)
            if (last_result and not last_result.healthy)
            else 1
        )

    session.add(
        HealthCheckResult(
            health_check_id=health_check.id,
            instance_id=instance.id,
            healthy=healthy,
            detail=detail,
            consecutive_failures=consecutive_failures,
            response_time_ms=response_time_ms,
            checked_at=now,
        )
    )
    session.commit()

    if not healthy and consecutive_failures >= health_check.unhealthy_threshold:
        await _heal(session, application, instance, health_check)


async def _heal(
    session: Session, application: Application, instance: Instance, health_check: HealthCheck
) -> None:
    try:
        lock_token = lock_service.acquire(session, application.id, "heal")
    except OperationLockHeldError:
        return  # a deploy/scale is in progress — retry healing on a later tick
    try:
        await self_healing_service.handle_unhealthy_instance(
            session, application, instance, health_check
        )
    finally:
        lock_service.release(session, application.id, lock_token)
