from datetime import UTC, datetime, timedelta

from app.db.models.metrics import MetricsSnapshot
from app.services.metrics_retention import cleanup_old_metrics
from tests.factories import make_server


def _snapshot(server_id, recorded_at):
    return MetricsSnapshot(
        server_id=server_id,
        cpu_percent=1.0,
        memory_percent=2.0,
        disk_percent=3.0,
        recorded_at=recorded_at,
    )


def test_cleanup_deletes_only_rows_past_the_retention_window(db_session):
    server = make_server(db_session)
    now = datetime.now(UTC)
    old = _snapshot(server.id, now - timedelta(days=10))
    recent = _snapshot(server.id, now - timedelta(hours=1))
    db_session.add_all([old, recent])
    db_session.flush()

    cleanup_old_metrics(db_session, retention_days=7)

    remaining = (
        db_session.query(MetricsSnapshot).filter(MetricsSnapshot.server_id == server.id).all()
    )
    assert [r.id for r in remaining] == [recent.id]


def test_cleanup_is_a_noop_for_rows_within_the_retention_window(db_session):
    server = make_server(db_session)
    snapshot = _snapshot(server.id, datetime.now(UTC))
    db_session.add(snapshot)
    db_session.flush()

    cleanup_old_metrics(db_session, retention_days=7)

    remaining = (
        db_session.query(MetricsSnapshot).filter(MetricsSnapshot.server_id == server.id).all()
    )
    assert [r.id for r in remaining] == [snapshot.id]
