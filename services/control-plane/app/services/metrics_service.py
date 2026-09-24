"""Read side for Phase 12's metrics: the dashboard's summary cards and
sparkline charts. Write side is agent_service.apply_heartbeat (unchanged);
retention/cleanup is metrics_retention.py.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.metrics import MetricsSnapshot

DEFAULT_HOURS = 6
MAX_HOURS = 24 * 7  # never exceed the retention window regardless of request
DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


def get_recent_metrics(
    session: Session,
    server_id: uuid.UUID,
    *,
    hours: int | None = None,
    limit: int | None = None,
) -> list[MetricsSnapshot]:
    hours = hours or DEFAULT_HOURS
    if hours <= 0 or hours > MAX_HOURS:
        hours = DEFAULT_HOURS
    limit = limit or DEFAULT_LIMIT
    if limit <= 0 or limit > MAX_LIMIT:
        limit = DEFAULT_LIMIT

    since = datetime.now(UTC) - timedelta(hours=hours)
    stmt = (
        select(MetricsSnapshot)
        .where(MetricsSnapshot.server_id == server_id, MetricsSnapshot.recorded_at >= since)
        .order_by(MetricsSnapshot.recorded_at.desc())
        .limit(limit)
    )
    rows = list(session.scalars(stmt).all())
    rows.reverse()  # oldest first, ready for a chart's x-axis
    return rows


def get_latest_metrics(session: Session, server_id: uuid.UUID) -> MetricsSnapshot | None:
    stmt = (
        select(MetricsSnapshot)
        .where(MetricsSnapshot.server_id == server_id)
        .order_by(MetricsSnapshot.recorded_at.desc())
    )
    return session.scalars(stmt).first()
