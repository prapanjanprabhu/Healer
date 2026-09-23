import asyncio
import json
import uuid

import httpx

from app.db.models.application import Instance
from app.db.models.domain import Domain
from app.db.models.enums import InstanceStatus
from app.services import gateway_service
from tests.factories import make_application, make_server


def _running_instance(session, application, server, port=9034) -> Instance:
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        port=port,
        status=InstanceStatus.RUNNING,
        service_name=f"Healer-{application.slug}-{port}",
    )
    session.add(instance)
    session.flush()
    return instance


def _domain(
    session,
    application,
    *,
    hostname=None,
    cert_path="/etc/healer/certs/a.crt",
    key_path="/etc/healer/certs/a.key",
) -> Domain:
    domain = Domain(
        application_id=application.id,
        hostname=hostname or f"{uuid.uuid4().hex[:8]}.healer.test",
        cert_path=cert_path,
        key_path=key_path,
    )
    session.add(domain)
    session.flush()
    return domain


def test_build_reload_payload_includes_only_running_instances_and_complete_domains(db_session):
    server = make_server(db_session)
    application = make_application(db_session)
    _domain(db_session, application, hostname="erp.healer.test")
    # A domain missing a key must never be sent to the Gateway Manager.
    Domain(
        application_id=application.id,
        hostname="incomplete.healer.test",
        cert_path="/etc/healer/certs/b.crt",
        key_path=None,
    )
    _running_instance(db_session, application, server, port=9034)
    db_session.add(
        Instance(
            application_id=application.id,
            server_id=server.id,
            port=9035,
            status=InstanceStatus.FAILED,
            service_name="not-included",
        )
    )
    db_session.flush()

    payload = gateway_service._build_reload_payload(db_session, application)

    assert payload["app_slug"] == application.slug
    assert payload["domains"] == [
        {
            "hostname": "erp.healer.test",
            "cert_path": "/etc/healer/certs/a.crt",
            "key_path": "/etc/healer/certs/a.key",
        }
    ]
    assert payload["upstreams"] == [{"host": server.hostname, "port": 9034}]


def test_sync_gateway_records_a_successful_reload(db_session):
    server = make_server(db_session)
    application = make_application(db_session)
    _domain(db_session, application)
    _running_instance(db_session, application, server)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/reload"
        assert request.headers["x-gateway-secret"]
        body = json.loads(request.content)
        assert body["app_slug"] == application.slug
        return httpx.Response(200, json={"ok": True, "message": "activated and reloaded"})

    result = asyncio.run(
        gateway_service.sync_gateway(
            db_session, application, transport=httpx.MockTransport(handler)
        )
    )

    assert result.ok is True
    assert result.message == "activated and reloaded"


def test_sync_gateway_reports_nginx_rejection_without_raising(db_session):
    application = make_application(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"ok": False, "message": "nginx -t rejected the new configuration"}
        )

    result = asyncio.run(
        gateway_service.sync_gateway(
            db_session, application, transport=httpx.MockTransport(handler)
        )
    )

    assert result.ok is False
    assert "rejected" in result.message


def test_sync_gateway_survives_an_unreachable_gateway_manager(db_session):
    application = make_application(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = asyncio.run(
        gateway_service.sync_gateway(
            db_session, application, transport=httpx.MockTransport(handler)
        )
    )

    assert result.ok is False
    assert "could not reach the Gateway Manager" in result.message
