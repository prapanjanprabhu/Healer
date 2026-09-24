import uuid
from datetime import UTC, datetime

from app.db.models.metrics import MetricsSnapshot
from tests.support.auth import login_as
from tests.support.csrf import csrf_headers


def _register_server(client, db_session) -> str:
    login_as(
        client,
        db_session,
        role="Administrator",
        email=f"admin-metrics-{uuid.uuid4().hex[:6]}@healer.test",
    )
    response = client.post(
        "/servers",
        json={
            "name": "metrics-target",
            "hostname": f"srv-{uuid.uuid4().hex[:8]}.internal",
            "os": "windows",
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_list_metrics_returns_recent_snapshots_oldest_first(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Viewer", email="viewer-metrics-1@healer.test")

    now = datetime.now(UTC)
    db_session.add(
        MetricsSnapshot(
            server_id=uuid.UUID(server_id),
            cpu_percent=10.0,
            memory_percent=20.0,
            disk_percent=30.0,
            recorded_at=now,
        )
    )
    db_session.flush()

    response = client.get(f"/servers/{server_id}/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["cpu_percent"] == 10.0
    assert body[0]["server_id"] == server_id


def test_list_metrics_404s_for_unknown_server(client, db_session):
    login_as(client, db_session, role="Viewer", email="viewer-metrics-2@healer.test")
    response = client.get(f"/servers/{uuid.uuid4()}/metrics")
    assert response.status_code == 404


def test_list_metrics_requires_authentication(client, db_session):
    response = client.get(f"/servers/{uuid.uuid4()}/metrics")
    assert response.status_code == 401
