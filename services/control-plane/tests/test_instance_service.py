"""Unit-level tests for instance_service's manual restart/stop actions.
Mocks command_service.submit_command_and_wait and gateway_service.sync_gateway
the same way test_release_service.py / test_self_healing_service.py do.
"""

import asyncio
from dataclasses import dataclass, field

import pytest

from app.db.models.application import Instance
from app.db.models.enums import AgentStatus, InstanceStatus
from app.services import instance_service
from app.services.gateway_service import GatewaySyncResult
from app.services.instance_service import InstanceActionError
from tests.factories import make_agent, make_application, make_release, make_server

WINDOWS_CONFIG = {
    "version": 1,
    "name": "Instance Action Test",
    "adapter": "windows-waitress-service",
    "source": {"type": "folder", "location": "C:\\HealerTest\\erp"},
    "windows": {
        "python_executable": "C:\\Python\\python.exe",
        "wsgi_module": "erp.wsgi",
        "settings_module": "erp.settings",
    },
    "health": {"path": "/health/"},
    "ports": {"start": 9400, "end": 9405},
    "secrets": [],
}


@dataclass
class _FakeCommandStatus:
    value: str


@dataclass
class _FakeCommand:
    status: _FakeCommandStatus
    error: str | None = None
    result: dict = field(default_factory=dict)


def _succeeded(result: dict | None = None) -> _FakeCommand:
    return _FakeCommand(status=_FakeCommandStatus("succeeded"), result=result or {"ok": True})


def _setup(session, *, instance_status=InstanceStatus.RUNNING):
    server = make_server(session)
    make_agent(session, server=server, status=AgentStatus.CONNECTED)
    application = make_application(
        session,
        server_id=server.id,
        port_range_start=9400,
        port_range_end=9405,
        config={**WINDOWS_CONFIG, "server_id": str(server.id)},
    )
    release = make_release(
        session,
        application=application,
        release_dir="C:\\ProgramData\\Healer\\apps\\instance-action-test\\releases\\v1",
        venv_python="C:\\ProgramData\\Healer\\apps\\instance-action-test\\releases\\v1\\.venv\\Scripts\\python.exe",
    )
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        release_id=release.id,
        port=9400,
        status=instance_status,
        service_name=f"Healer-{application.slug}-9400",
    )
    session.add(instance)
    session.flush()
    return application, instance


def _mock_submit(monkeypatch, fake_command):
    async def fake_submit(
        session, agent, command_type, payload, *, idempotency_key, ttl_seconds, wait_seconds
    ):
        return fake_command

    monkeypatch.setattr(instance_service.command_service, "submit_command_and_wait", fake_submit)


def _mock_gateway(monkeypatch):
    async def fake_sync_gateway(session, application, *, actor_id=None, transport=None):
        return GatewaySyncResult(ok=True, message="activated and reloaded")

    monkeypatch.setattr(instance_service.gateway_service, "sync_gateway", fake_sync_gateway)


def test_restart_instance_succeeds_and_returns_to_running(db_session, monkeypatch):
    application, instance = _setup(db_session)
    _mock_submit(monkeypatch, _succeeded())
    _mock_gateway(monkeypatch)

    asyncio.run(instance_service.restart_instance(db_session, application, instance))

    assert instance.status == InstanceStatus.RUNNING
    assert instance.failure_reason is None


def test_restart_instance_marks_failed_on_agent_error(db_session, monkeypatch):
    application, instance = _setup(db_session)
    _mock_submit(monkeypatch, _FakeCommand(status=_FakeCommandStatus("failed"), error="boom"))
    _mock_gateway(monkeypatch)

    with pytest.raises(InstanceActionError, match="boom"):
        asyncio.run(instance_service.restart_instance(db_session, application, instance))

    assert instance.status == InstanceStatus.FAILED
    assert instance.failure_reason == "boom"


def test_restart_instance_rejects_a_stopped_instance(db_session, monkeypatch):
    application, instance = _setup(db_session, instance_status=InstanceStatus.STOPPED)

    with pytest.raises(InstanceActionError, match="not in a state"):
        asyncio.run(instance_service.restart_instance(db_session, application, instance))


def test_restart_instance_rejects_a_disconnected_agent(db_session, monkeypatch):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.DISCONNECTED)
    application = make_application(
        db_session,
        server_id=server.id,
        port_range_start=9400,
        port_range_end=9405,
        config={**WINDOWS_CONFIG, "server_id": str(server.id)},
    )
    release = make_release(
        db_session, application=application, release_dir="C:\\x", venv_python="C:\\x\\python.exe"
    )
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        release_id=release.id,
        port=9400,
        status=InstanceStatus.RUNNING,
        service_name="Healer-x-9400",
    )
    db_session.add(instance)
    db_session.flush()

    with pytest.raises(InstanceActionError, match="not currently connected"):
        asyncio.run(instance_service.restart_instance(db_session, application, instance))


def test_stop_instance_succeeds(db_session, monkeypatch):
    application, instance = _setup(db_session)
    _mock_submit(monkeypatch, _succeeded())
    _mock_gateway(monkeypatch)

    asyncio.run(instance_service.stop_instance(db_session, application, instance))

    assert instance.status == InstanceStatus.STOPPED


def test_stop_instance_marks_failed_on_agent_error(db_session, monkeypatch):
    application, instance = _setup(db_session)
    _mock_submit(
        monkeypatch, _FakeCommand(status=_FakeCommandStatus("failed"), error="stop failed")
    )
    _mock_gateway(monkeypatch)

    with pytest.raises(InstanceActionError, match="stop failed"):
        asyncio.run(instance_service.stop_instance(db_session, application, instance))

    assert instance.status == InstanceStatus.FAILED


def test_stop_instance_rejects_an_already_stopped_instance(db_session):
    application, instance = _setup(db_session, instance_status=InstanceStatus.FAILED)

    with pytest.raises(InstanceActionError, match="not in a state"):
        asyncio.run(instance_service.stop_instance(db_session, application, instance))
