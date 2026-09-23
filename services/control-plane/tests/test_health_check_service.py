import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.db.models.application import Application, Instance
from app.db.models.enums import HealthCheckType, InstanceStatus
from app.db.models.health import HealthCheck, HealthCheckResult
from app.services import health_check_service
from tests.factories import make_application, make_server


class _Handler(BaseHTTPRequestHandler):
    status_code = 200

    def do_GET(self):  # noqa: N802 - required name by BaseHTTPRequestHandler
        self.send_response(self.status_code)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002 - silence test server logging
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


def test_check_instance_once_reports_healthy_for_a_real_2xx_response(real_http_server):
    _Handler.status_code = 200
    port = real_http_server.server_address[1]

    healthy, detail, response_time_ms = health_check_service.check_instance_once(
        "127.0.0.1", port, "/", timeout_seconds=2.0
    )

    assert healthy is True
    assert detail == "HTTP 200"
    assert response_time_ms is not None and response_time_ms >= 0


def test_check_instance_once_reports_unhealthy_for_a_real_5xx_response(real_http_server):
    _Handler.status_code = 503
    port = real_http_server.server_address[1]

    healthy, detail, _ = health_check_service.check_instance_once(
        "127.0.0.1", port, "/", timeout_seconds=2.0
    )

    assert healthy is False
    assert detail == "HTTP 503"


def test_check_instance_once_reports_unhealthy_when_nothing_is_listening():
    healthy, detail, response_time_ms = health_check_service.check_instance_once(
        "127.0.0.1", 1, "/", timeout_seconds=1.0
    )
    assert healthy is False
    assert response_time_ms is None
    assert detail


def _instance(session, application: Application, *, port: int = 9034) -> Instance:
    server = make_server(session)
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        port=port,
        status=InstanceStatus.STARTING,
        service_name=f"Healer-{application.slug}-{port}",
    )
    session.add(instance)
    session.flush()
    return instance


def _health_check(session, application: Application, **overrides) -> HealthCheck:
    defaults = dict(
        application_id=application.id,
        check_type=HealthCheckType.HTTP,
        path="/",
        interval_seconds=0,
        timeout_seconds=2,
        healthy_threshold=2,
        unhealthy_threshold=2,
    )
    defaults.update(overrides)
    check = HealthCheck(**defaults)
    session.add(check)
    session.flush()
    return check


def test_wait_until_healthy_returns_true_and_records_results_for_a_real_healthy_server(
    db_session, real_http_server
):
    _Handler.status_code = 200
    port = real_http_server.server_address[1]
    application = make_application(db_session)
    health_check = _health_check(db_session, application)
    instance = _instance(db_session, application)

    result = health_check_service.wait_until_healthy(
        db_session, health_check, instance.id, host="127.0.0.1", port=port
    )

    assert result is True
    results = (
        db_session.query(HealthCheckResult)
        .filter(HealthCheckResult.instance_id == instance.id)
        .order_by(HealthCheckResult.checked_at)
        .all()
    )
    assert len(results) == 2  # healthy_threshold consecutive successes, no more
    assert all(r.healthy for r in results)
    assert all(r.response_time_ms is not None for r in results)


def test_wait_until_healthy_returns_false_when_nothing_is_listening(db_session):
    application = make_application(db_session)
    health_check = _health_check(
        db_session, application, unhealthy_threshold=2, healthy_threshold=2
    )
    instance = _instance(db_session, application)

    result = health_check_service.wait_until_healthy(
        db_session, health_check, instance.id, host="127.0.0.1", port=1
    )

    assert result is False
    results = (
        db_session.query(HealthCheckResult)
        .filter(HealthCheckResult.instance_id == instance.id)
        .all()
    )
    assert len(results) == 2  # unhealthy_threshold consecutive failures, no more
    assert all(not r.healthy for r in results)
    assert all(r.consecutive_failures == i + 1 for i, r in enumerate(results))
