"""Unit-level tests for self_healing_service's own remediation logic.

command_service.submit_command_and_wait is mocked here rather than driven
through a real WebSocket/FakeAgent round trip — the Agent command plumbing
itself is already proven by the deploy/scale test suites (and, for this
phase specifically, by genuine live verification: killing a real Waitress
process on the real Windows machine). What these tests exercise is
self_healing_service's own state-machine/bookkeeping logic: removal from
the gateway, the cooldown/attempt-limit bound, the replacement lineage, and
giving up with a notification — see docs/self-healing.md.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.db.models.application import Instance
from app.db.models.enums import AgentStatus, InstanceStatus
from app.db.models.health import HealthCheck
from app.db.models.notification import Notification
from app.services import self_healing_service
from app.services.gateway_service import GatewaySyncResult
from tests.factories import make_agent, make_application, make_release, make_server


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


def _failed(error: str = "boom") -> _FakeCommand:
    return _FakeCommand(status=_FakeCommandStatus("failed"), error=error)


def _valid_config(server_id) -> dict:
    return {
        "version": 1,
        "name": "Heal Test ERP",
        "adapter": "windows-waitress-service",
        "server_id": str(server_id),
        "source": {"type": "folder", "location": "C:\\HealerTest\\erp", "ref": None},
        "windows": {
            "python_executable": "C:\\Python\\python.exe",
            "requirements_file": "requirements.txt",
            "manage_py": "manage.py",
            "wsgi_module": "erp.wsgi",
            "settings_module": "erp.settings",
            "static_dir": "static",
            "media_dir": "media",
            "log_dir": "logs",
            "exclude": [],
        },
        "linux": None,
        "health": {
            "path": "/health/",
            "interval_seconds": 10,
            "timeout_seconds": 5,
            "healthy_threshold": 2,
            "unhealthy_threshold": 3,
        },
        "ports": {"start": 9034, "end": 9039},
        "replicas": {"min": 1, "max": 6},
        "domain": {"hostname": "erp-heal.ritrjpm.edu.in", "cert_path": None, "key_path": None},
        "secrets": [],
    }


def _setup(session, **hc_overrides):
    server = make_server(session)
    make_agent(session, server=server, status=AgentStatus.CONNECTED)
    application = make_application(
        session,
        server_id=server.id,
        port_range_start=9034,
        port_range_end=9039,
        config=_valid_config(server.id),
    )
    release = make_release(
        session,
        application=application,
        release_dir="C:\\ProgramData\\Healer\\apps\\heal-test-erp\\releases\\20260101000000",
        venv_python=(
            "C:\\ProgramData\\Healer\\apps\\heal-test-erp\\releases\\20260101000000"
            "\\.venv\\Scripts\\python.exe"
        ),
    )
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        release_id=release.id,
        port=9034,
        status=InstanceStatus.RUNNING,
        service_name=f"Healer-{application.slug}-9034",
    )
    session.add(instance)
    session.flush()

    defaults = dict(
        application_id=application.id,
        path="/health/",
        interval_seconds=0,
        timeout_seconds=1,
        healthy_threshold=1,
        unhealthy_threshold=1,
        max_restart_attempts=3,
        restart_cooldown_seconds=0,
    )
    defaults.update(hc_overrides)
    health_check = HealthCheck(**defaults)
    session.add(health_check)
    session.flush()
    session.commit()
    return application, instance, health_check


def _gateway_mock(monkeypatch):
    calls = []

    async def fake_sync_gateway(session, application, *, actor_id=None, transport=None):
        calls.append(None)
        return GatewaySyncResult(ok=True, message="activated and reloaded")

    monkeypatch.setattr(self_healing_service.gateway_service, "sync_gateway", fake_sync_gateway)
    return calls


def test_restart_recovers_a_running_instance(db_session, monkeypatch):
    application, instance, health_check = _setup(db_session)
    gateway_calls = _gateway_mock(monkeypatch)

    async def fake_submit(*a, **k):
        return _succeeded(
            {
                "ok": True,
                "steps": [{"name": "service_start", "status": "succeeded", "message": "running"}],
            }
        )

    monkeypatch.setattr(
        self_healing_service.command_service, "submit_command_and_wait", fake_submit
    )
    monkeypatch.setattr(
        self_healing_service.health_check_service, "wait_until_healthy", lambda *a, **k: True
    )

    asyncio.run(
        self_healing_service.handle_unhealthy_instance(
            db_session, application, instance, health_check
        )
    )

    db_session.refresh(instance)
    assert instance.status == InstanceStatus.RUNNING
    assert instance.healing_attempts == 1
    assert instance.failure_reason is None
    assert len(gateway_calls) == 2  # once to remove (unhealthy), once to re-add (recovered)


def test_restart_command_failure_creates_a_healthy_replacement(db_session, monkeypatch):
    application, instance, health_check = _setup(db_session)
    original_port = instance.port
    _gateway_mock(monkeypatch)

    async def fake_submit(*a, **k):
        return _succeeded({"ok": True, "steps": []})

    monkeypatch.setattr(
        self_healing_service.command_service, "submit_command_and_wait", fake_submit
    )
    # The restart's own health verification fails; the replacement's succeeds.
    health_results = iter([False, True])
    monkeypatch.setattr(
        self_healing_service.health_check_service,
        "wait_until_healthy",
        lambda *a, **k: next(health_results),
    )

    asyncio.run(
        self_healing_service.handle_unhealthy_instance(
            db_session, application, instance, health_check
        )
    )

    db_session.refresh(instance)
    assert instance.status == InstanceStatus.FAILED
    assert instance.failure_reason == "restart did not restore a healthy instance"

    replacement = (
        db_session.query(Instance)
        .filter(Instance.application_id == application.id, Instance.id != instance.id)
        .one()
    )
    assert replacement.port != original_port
    assert replacement.status == InstanceStatus.RUNNING
    assert replacement.healing_attempts == instance.healing_attempts == 1


def test_replacement_start_failure_gives_up_and_notifies(db_session, monkeypatch):
    application, instance, health_check = _setup(db_session)
    _gateway_mock(monkeypatch)

    calls = {"n": 0}

    async def fake_submit(*a, **k):
        calls["n"] += 1
        # First call: restart's own start_instance succeeds (but never
        # becomes healthy, forcing a replacement). Second call: the
        # replacement's start_instance fails outright.
        if calls["n"] == 1:
            return _succeeded({"ok": True, "steps": []})
        return _failed("agent unreachable")

    monkeypatch.setattr(
        self_healing_service.command_service, "submit_command_and_wait", fake_submit
    )
    monkeypatch.setattr(
        self_healing_service.health_check_service, "wait_until_healthy", lambda *a, **k: False
    )

    asyncio.run(
        self_healing_service.handle_unhealthy_instance(
            db_session, application, instance, health_check
        )
    )

    db_session.refresh(instance)
    assert instance.status == InstanceStatus.FAILED

    replacement = (
        db_session.query(Instance)
        .filter(Instance.application_id == application.id, Instance.id != instance.id)
        .one()
    )
    assert replacement.status == InstanceStatus.FAILED
    assert replacement.failure_reason == "replacement instance failed to start"

    notification = (
        db_session.query(Notification)
        .filter(Notification.notification_type == "self_healing_gave_up")
        .one()
    )
    assert str(replacement.port) in notification.message


def test_max_attempts_reached_gives_up_without_attempting_a_restart(db_session, monkeypatch):
    application, instance, health_check = _setup(db_session)
    _gateway_mock(monkeypatch)
    instance.healing_attempts = health_check.max_restart_attempts
    db_session.commit()

    async def fake_submit(*a, **k):
        raise AssertionError("must not attempt a restart once the limit is reached")

    monkeypatch.setattr(
        self_healing_service.command_service, "submit_command_and_wait", fake_submit
    )

    asyncio.run(
        self_healing_service.handle_unhealthy_instance(
            db_session, application, instance, health_check
        )
    )

    db_session.refresh(instance)
    assert instance.status == InstanceStatus.FAILED
    assert instance.failure_reason == "maximum restart attempts reached"

    notification = (
        db_session.query(Notification)
        .filter(Notification.notification_type == "self_healing_gave_up")
        .one()
    )
    assert str(instance.port) in notification.message


def test_cooldown_defers_healing_without_incrementing_attempts(db_session, monkeypatch):
    application, instance, health_check = _setup(db_session, restart_cooldown_seconds=3600)
    _gateway_mock(monkeypatch)
    instance.last_healing_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    async def fake_submit(*a, **k):
        raise AssertionError("must not attempt a restart during the cooldown window")

    monkeypatch.setattr(
        self_healing_service.command_service, "submit_command_and_wait", fake_submit
    )

    asyncio.run(
        self_healing_service.handle_unhealthy_instance(
            db_session, application, instance, health_check
        )
    )

    db_session.refresh(instance)
    # Removed from the gateway (now UNHEALTHY) but no restart attempted yet.
    assert instance.status == InstanceStatus.UNHEALTHY
    assert instance.healing_attempts == 0


def test_no_connected_agent_gives_up_immediately(db_session, monkeypatch):
    application, instance, health_check = _setup(db_session)
    _gateway_mock(monkeypatch)
    from app.db.models.agent import Agent

    db_session.query(Agent).filter(Agent.server_id == instance.server_id).update(
        {"status": AgentStatus.DISCONNECTED}
    )
    db_session.commit()

    asyncio.run(
        self_healing_service.handle_unhealthy_instance(
            db_session, application, instance, health_check
        )
    )

    db_session.refresh(instance)
    assert instance.status == InstanceStatus.FAILED
    assert instance.failure_reason == "the target server's Agent is not connected"
