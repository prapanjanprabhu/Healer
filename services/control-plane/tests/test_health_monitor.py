"""Tests for the continuous health-check loop's own gating/wiring logic —
real HTTP polling against a real local server (same pattern as
test_health_check_service.py), with self_healing_service mocked out since
its own remediation logic is covered by test_self_healing_service.py.

health_monitor.tick() always opens its own fresh SessionLocal() (matching
production — see health_monitor.py's own docstring on why), a genuinely
separate DB connection from the `db_session` fixture's savepoint-based one
used everywhere else in this suite. Since that fixture's "commits" never
actually reach Postgres until the fixture rolls back at teardown, tick()'s
own connection can't see anything set up through it. These tests use a
real, actually-committing SessionLocal() instead, with explicit cleanup.
"""

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.db.models.application import Instance
from app.db.models.enums import AgentStatus, InstanceStatus
from app.db.models.health import HealthCheck, HealthCheckResult
from app.db.session import SessionLocal
from app.services import health_monitor
from tests.factories import make_agent, make_application, make_server


class _Handler(BaseHTTPRequestHandler):
    status_code = 200

    def do_GET(self):  # noqa: N802
        self.send_response(self.status_code)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass


@pytest.fixture()
def real_http_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def real_session():
    """A genuinely committing session on its own connection — see the
    module docstring on why `db_session` can't be used here.
    """
    session = SessionLocal()
    created = []
    try:
        yield session, created
    finally:
        for obj in reversed(created):
            session.delete(obj)
        session.commit()
        session.close()


def _setup(session, created, *, port: int, **hc_overrides):
    server = make_server(session, hostname="127.0.0.1")
    make_agent(session, server=server, status=AgentStatus.CONNECTED)
    application = make_application(session, server_id=server.id)
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        port=port,
        status=InstanceStatus.RUNNING,
        service_name=f"Healer-{application.slug}-{port}",
    )
    session.add(instance)
    session.flush()
    defaults = dict(
        application_id=application.id,
        path="/",
        interval_seconds=60,
        timeout_seconds=1,
        healthy_threshold=2,
        unhealthy_threshold=2,
    )
    defaults.update(hc_overrides)
    health_check = HealthCheck(**defaults)
    session.add(health_check)
    session.flush()
    session.commit()
    created.append(application)  # cascades instance + health_check + results
    created.append(server)  # cascades agent
    return application, instance, health_check


def test_tick_polls_a_running_instance_and_records_a_healthy_result(real_http_server, real_session):
    session, created = real_session
    _Handler.status_code = 200
    port = real_http_server.server_address[1]
    application, instance, health_check = _setup(session, created, port=port)

    asyncio.run(health_monitor.tick())

    results = (
        session.query(HealthCheckResult).filter(HealthCheckResult.instance_id == instance.id).all()
    )
    assert len(results) == 1
    assert results[0].healthy is True


def test_tick_skips_an_instance_whose_interval_has_not_elapsed(real_http_server, real_session):
    session, created = real_session
    _Handler.status_code = 200
    port = real_http_server.server_address[1]
    application, instance, health_check = _setup(session, created, port=port, interval_seconds=3600)
    session.add(
        HealthCheckResult(
            health_check_id=health_check.id,
            instance_id=instance.id,
            healthy=True,
            detail="HTTP 200",
            consecutive_failures=0,
            response_time_ms=5,
            checked_at=datetime.now(UTC),
        )
    )
    session.commit()

    asyncio.run(health_monitor.tick())

    results = (
        session.query(HealthCheckResult).filter(HealthCheckResult.instance_id == instance.id).all()
    )
    assert len(results) == 1  # the pre-seeded one only — no new poll was due


def test_tick_polls_again_once_the_interval_has_elapsed(real_http_server, real_session):
    session, created = real_session
    _Handler.status_code = 200
    port = real_http_server.server_address[1]
    application, instance, health_check = _setup(session, created, port=port, interval_seconds=1)
    session.add(
        HealthCheckResult(
            health_check_id=health_check.id,
            instance_id=instance.id,
            healthy=True,
            detail="HTTP 200",
            consecutive_failures=0,
            response_time_ms=5,
            checked_at=datetime.now(UTC) - timedelta(seconds=2),
        )
    )
    session.commit()

    asyncio.run(health_monitor.tick())

    results = (
        session.query(HealthCheckResult).filter(HealthCheckResult.instance_id == instance.id).all()
    )
    assert len(results) == 2


def test_tick_hands_off_to_self_healing_once_the_unhealthy_threshold_is_crossed(
    real_session, monkeypatch
):
    session, created = real_session
    # Nothing is listening on this port — every poll fails immediately.
    application, instance, health_check = _setup(
        session, created, port=1, unhealthy_threshold=2, interval_seconds=0
    )

    calls = []

    async def fake_heal(session, application, instance, health_check):
        calls.append(instance.id)

    monkeypatch.setattr(health_monitor.self_healing_service, "handle_unhealthy_instance", fake_heal)

    asyncio.run(health_monitor.tick())
    assert calls == []  # first failure only — threshold not yet crossed

    asyncio.run(health_monitor.tick())
    assert calls == [instance.id]  # second consecutive failure crosses unhealthy_threshold=2


def test_tick_retries_an_already_unhealthy_instance_every_tick(real_session, monkeypatch):
    session, created = real_session
    application, instance, health_check = _setup(session, created, port=1)
    session.query(Instance).filter(Instance.id == instance.id).update(
        {"status": InstanceStatus.UNHEALTHY}
    )
    session.commit()

    calls = []

    async def fake_heal(session, application, instance, health_check):
        calls.append(instance.id)

    monkeypatch.setattr(health_monitor.self_healing_service, "handle_unhealthy_instance", fake_heal)

    asyncio.run(health_monitor.tick())
    assert calls == [instance.id]
