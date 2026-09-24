from datetime import UTC, datetime, timedelta

from app.db.models.metrics import MetricsSnapshot
from app.services import metrics_service
from tests.factories import make_server


def _snapshot(server_id, recorded_at, cpu=10.0):
    return MetricsSnapshot(
        server_id=server_id,
        cpu_percent=cpu,
        memory_percent=20.0,
        disk_percent=30.0,
        recorded_at=recorded_at,
    )


def test_get_recent_metrics_returns_oldest_first_within_the_window(db_session):
    server = make_server(db_session)
    now = datetime.now(UTC)
    older = _snapshot(server.id, now - timedelta(hours=2), cpu=11.0)
    newer = _snapshot(server.id, now - timedelta(minutes=5), cpu=22.0)
    too_old = _snapshot(server.id, now - timedelta(hours=48), cpu=99.0)
    db_session.add_all([older, newer, too_old])
    db_session.flush()

    rows = metrics_service.get_recent_metrics(db_session, server.id, hours=6)

    assert [float(r.cpu_percent) for r in rows] == [11.0, 22.0]


def test_get_recent_metrics_ignores_other_servers(db_session):
    server_a = make_server(db_session)
    server_b = make_server(db_session)
    db_session.add(_snapshot(server_a.id, datetime.now(UTC), cpu=5.0))
    db_session.add(_snapshot(server_b.id, datetime.now(UTC), cpu=50.0))
    db_session.flush()

    rows = metrics_service.get_recent_metrics(db_session, server_a.id)

    assert len(rows) == 1
    assert float(rows[0].cpu_percent) == 5.0


def test_get_recent_metrics_clamps_absurd_hours_and_limit(db_session):
    server = make_server(db_session)
    db_session.add(_snapshot(server.id, datetime.now(UTC)))
    db_session.flush()

    rows = metrics_service.get_recent_metrics(db_session, server.id, hours=999999, limit=-5)

    assert len(rows) == 1


def test_get_latest_metrics_returns_the_most_recent_row(db_session):
    server = make_server(db_session)
    now = datetime.now(UTC)
    db_session.add(_snapshot(server.id, now - timedelta(minutes=10), cpu=1.0))
    db_session.add(_snapshot(server.id, now, cpu=2.0))
    db_session.flush()

    latest = metrics_service.get_latest_metrics(db_session, server.id)

    assert latest is not None
    assert float(latest.cpu_percent) == 2.0


def test_get_latest_metrics_returns_none_when_no_data(db_session):
    server = make_server(db_session)
    assert metrics_service.get_latest_metrics(db_session, server.id) is None
