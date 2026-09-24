"""Short-term metrics retention — see docs/metrics-and-logs.md.

MetricsSnapshot rows arrive every heartbeat (every ~20s per connected Agent,
apply_heartbeat in agent_service.py) and are never read back by anything
older than settings.metrics_retention_days, so this background loop simply
deletes rows past that window on a slow, fixed cadence. Runs the same way
health_monitor does: its own asyncio task in this process, its own
SessionLocal per pass, gated by the same settings.health_monitor_enabled
flag (see app/main.py's lifespan) so it never runs during the test suite.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.db.models.metrics import MetricsSnapshot
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 3600.0


async def run_forever() -> None:
    while True:
        try:
            await asyncio.to_thread(cleanup_once)
        except Exception:
            logger.exception("metrics retention cleanup failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


def cleanup_once() -> int:
    session = SessionLocal()
    try:
        return cleanup_old_metrics(session, settings.metrics_retention_days)
    finally:
        session.close()


def cleanup_old_metrics(session, retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted = (
        session.query(MetricsSnapshot)
        .filter(MetricsSnapshot.recorded_at < cutoff)
        .delete(synchronize_session=False)
    )
    session.commit()
    if deleted:
        logger.info(
            "metrics retention: deleted %d snapshot(s) older than %d day(s)",
            deleted,
            retention_days,
        )
    return deleted
