"""Unit-level tests for release_service's blue-green switch and rollback.

command_service.submit_command_and_wait is mocked (same rationale as
test_self_healing_service.py) — the Agent command plumbing itself is
already proven by the deploy/scale/self-healing test suites and, for this
phase, by genuine live verification. What these tests exercise is
release_service's own orchestration: the all-or-nothing health gate, the
atomic switch (and its revert), that a failure never touches the old
release's traffic, rollback reusing an existing release without rebuilding,
and retention pruning.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.db.models.application import Instance, Source
from app.db.models.enums import (
    AgentCommandType,
    AgentStatus,
    InstanceStatus,
    ReleaseStatus,
    SourceType,
)
from app.db.models.health import HealthCheck
from app.services import release_service
from app.services.gateway_service import GatewaySyncResult
from app.services.release_service import ReleaseSetupError
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


def _deploy_release_result(release_dir: str, venv_python: str) -> dict:
    return {"ok": True, "steps": [], "release_dir": release_dir, "venv_python": venv_python}


def _valid_config(server_id) -> dict:
    return {
        "version": 1,
        "name": "BG Test ERP",
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
            "interval_seconds": 1,
            "timeout_seconds": 1,
            "healthy_threshold": 1,
            "unhealthy_threshold": 1,
        },
        "ports": {"start": 9034, "end": 9045},
        "replicas": {"min": 1, "max": 4},
        "domain": {"hostname": "erp-bg.ritrjpm.edu.in", "cert_path": None, "key_path": None},
        "secrets": [],
    }


def _setup(session, *, replicas: int = 2, retention: int = 5):
    server = make_server(session)
    make_agent(session, server=server, status=AgentStatus.CONNECTED)
    application = make_application(
        session,
        server_id=server.id,
        port_range_start=9034,
        port_range_end=9045,
        min_replicas=1,
        max_replicas=4,
        desired_replicas=replicas,
        release_retention_count=retention,
        config=_valid_config(server.id),
    )
    session.add(
        Source(
            application_id=application.id,
            source_type=SourceType.FOLDER,
            location="C:\\HealerTest\\erp",
        )
    )
    session.flush()
    old_release = make_release(
        session,
        application=application,
        ref="v1",
        release_dir="C:\\ProgramData\\Healer\\apps\\bg-test-erp\\releases\\v1",
        venv_python="C:\\ProgramData\\Healer\\apps\\bg-test-erp\\releases\\v1\\.venv\\Scripts\\python.exe",
    )
    application.active_release_id = old_release.id
    session.add(
        HealthCheck(
            application_id=application.id,
            path="/health/",
            interval_seconds=0,
            timeout_seconds=1,
            healthy_threshold=1,
            unhealthy_threshold=1,
        )
    )
    old_instances = []
    for i in range(replicas):
        port = 9034 + i
        instance = Instance(
            application_id=application.id,
            server_id=server.id,
            release_id=old_release.id,
            port=port,
            status=InstanceStatus.RUNNING,
            service_name=f"Healer-bg-test-erp-{port}",
        )
        session.add(instance)
        old_instances.append(instance)
    session.flush()
    session.commit()
    return application, old_release, old_instances


def _gateway_mock(monkeypatch, *, ok: bool = True, message: str = "activated and reloaded"):
    calls = []

    async def fake_sync_gateway(session, application, *, actor_id=None, transport=None):
        calls.append(None)
        return GatewaySyncResult(ok=ok, message=message)

    monkeypatch.setattr(release_service.gateway_service, "sync_gateway", fake_sync_gateway)
    return calls


def _mock_commands(
    monkeypatch,
    *,
    start_ok=True,
    healthy=True,
    new_release_dir="C:\\new\\release",
    new_venv="C:\\new\\release\\.venv\\Scripts\\python.exe",
):
    sent = {"deploy_release": 0, "start_instance": 0, "stop_instance": 0}

    async def fake_submit(
        session, agent, command_type, payload, *, idempotency_key, ttl_seconds, wait_seconds
    ):
        if command_type == AgentCommandType.DEPLOY_RELEASE:
            sent["deploy_release"] += 1
            return _succeeded(_deploy_release_result(new_release_dir, new_venv))
        if command_type == AgentCommandType.START_INSTANCE:
            sent["start_instance"] += 1
            return _succeeded({"ok": start_ok, "steps": []})
        if command_type == AgentCommandType.STOP_INSTANCE:
            sent["stop_instance"] += 1
            return _succeeded({"ok": True, "steps": []})
        raise AssertionError(f"unexpected command type {command_type}")

    monkeypatch.setattr(release_service.command_service, "submit_command_and_wait", fake_submit)
    monkeypatch.setattr(
        release_service.health_check_service, "wait_until_healthy", lambda *a, **k: healthy
    )
    return sent


def test_start_new_release_rejects_an_application_with_no_active_release(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    application = make_application(db_session, server_id=server.id, config=_valid_config(server.id))
    try:
        release_service.start_new_release(db_session, application, None, actor_id=None)
        assert False, "expected ReleaseSetupError"
    except ReleaseSetupError as exc:
        assert "no active release" in str(exc)


def test_successful_blue_green_switch_starts_new_instances_and_drains_old(db_session, monkeypatch):
    application, old_release, old_instances = _setup(db_session, replicas=2)
    gateway_calls = _gateway_mock(monkeypatch)
    sent = _mock_commands(monkeypatch)
    monkeypatch.setattr(release_service, "DEFAULT_DRAIN_TIMEOUT_SECONDS", 0)

    from app.services import application_service

    config = application_service.config_from_application(application)
    deployment = release_service.start_new_release(db_session, application, config, actor_id=None)
    assert deployment.kind == "blue_green"

    asyncio.run(release_service.run_release_switch(db_session, deployment.id, datetime.now(UTC)))

    db_session.refresh(deployment)
    assert deployment.status.value == "succeeded"
    assert sent["deploy_release"] == 1
    assert sent["start_instance"] == 2  # the two new instances
    assert sent["stop_instance"] == 2  # the two old instances, drained afterward

    db_session.refresh(application)
    assert application.active_release_id != old_release.id

    new_instances = (
        db_session.query(Instance)
        .filter(Instance.release_id == application.active_release_id)
        .all()
    )
    assert len(new_instances) == 2
    assert all(i.status == InstanceStatus.RUNNING for i in new_instances)
    assert {i.port for i in new_instances} == {9036, 9037}  # next free ports after 9034/9035

    for old_instance in old_instances:
        db_session.refresh(old_instance)
        assert old_instance.status == InstanceStatus.STOPPED

    assert len(gateway_calls) == 1


def test_failed_health_check_never_touches_the_old_release(db_session, monkeypatch):
    application, old_release, old_instances = _setup(db_session, replicas=2)
    gateway_calls = _gateway_mock(monkeypatch)
    _mock_commands(monkeypatch, healthy=False)

    from app.services import application_service

    config = application_service.config_from_application(application)
    deployment = release_service.start_new_release(db_session, application, config, actor_id=None)
    asyncio.run(release_service.run_release_switch(db_session, deployment.id, datetime.now(UTC)))

    db_session.refresh(deployment)
    assert deployment.status.value == "failed"
    assert "healthy" in deployment.failure_reason

    db_session.refresh(application)
    assert application.active_release_id == old_release.id  # never switched
    assert len(gateway_calls) == 0  # never even reached the gateway step

    for old_instance in old_instances:
        db_session.refresh(old_instance)
        assert old_instance.status == InstanceStatus.RUNNING  # completely untouched

    new_instances = (
        db_session.query(Instance)
        .filter(Instance.application_id == application.id, Instance.release_id != old_release.id)
        .all()
    )
    assert len(new_instances) == 1  # the first one to fail — the gate aborts immediately
    assert new_instances[0].status == InstanceStatus.FAILED


def test_failed_gateway_validation_reverts_the_switch_and_preserves_old_traffic(
    db_session, monkeypatch
):
    application, old_release, old_instances = _setup(db_session, replicas=2)
    gateway_calls = _gateway_mock(
        monkeypatch, ok=False, message="nginx -t rejected the new configuration"
    )
    _mock_commands(monkeypatch)

    from app.services import application_service

    config = application_service.config_from_application(application)
    deployment = release_service.start_new_release(db_session, application, config, actor_id=None)
    asyncio.run(release_service.run_release_switch(db_session, deployment.id, datetime.now(UTC)))

    db_session.refresh(deployment)
    assert deployment.status.value == "failed"
    assert "nginx -t rejected" in deployment.failure_reason

    db_session.refresh(application)
    assert application.active_release_id == old_release.id  # reverted back
    assert len(gateway_calls) == 1

    for old_instance in old_instances:
        db_session.refresh(old_instance)
        assert (
            old_instance.status == InstanceStatus.RUNNING
        )  # never drained — switch never took effect

    new_instances = (
        db_session.query(Instance)
        .filter(Instance.application_id == application.id, Instance.release_id != old_release.id)
        .all()
    )
    assert len(new_instances) == 2
    assert all(i.status == InstanceStatus.STOPPED for i in new_instances)  # cleaned up


def test_rollback_reuses_the_existing_release_without_rebuilding(db_session, monkeypatch):
    application, release_a, release_a_instances = _setup(db_session, replicas=2)
    _gateway_mock(monkeypatch)
    sent = _mock_commands(monkeypatch)
    monkeypatch.setattr(release_service, "DEFAULT_DRAIN_TIMEOUT_SECONDS", 0)

    from app.services import application_service

    config = application_service.config_from_application(application)
    deployment = release_service.start_new_release(db_session, application, config, actor_id=None)
    asyncio.run(release_service.run_release_switch(db_session, deployment.id, datetime.now(UTC)))
    db_session.refresh(application)
    release_b_id = application.active_release_id
    assert release_b_id != release_a.id

    sent["deploy_release"] = 0  # reset the counter before rolling back

    rollback_deployment = release_service.start_rollback(
        db_session, application, release_a.id, actor_id=None
    )
    assert rollback_deployment.kind == "rollback"
    asyncio.run(release_service.run_release_switch(db_session, rollback_deployment.id, datetime.now(UTC)))

    assert sent["deploy_release"] == 0  # rollback never rebuilds

    db_session.refresh(application)
    assert application.active_release_id == release_a.id

    reactivated = (
        db_session.query(Instance)
        .filter(Instance.release_id == release_a.id, Instance.status == InstanceStatus.RUNNING)
        .all()
    )
    assert len(reactivated) == 2

    release_b_instances = (
        db_session.query(Instance).filter(Instance.release_id == release_b_id).all()
    )
    assert all(i.status == InstanceStatus.STOPPED for i in release_b_instances)


def test_cannot_roll_back_to_the_already_active_release(db_session):
    application, old_release, _ = _setup(db_session)
    try:
        release_service.start_rollback(db_session, application, old_release.id, actor_id=None)
        assert False, "expected ReleaseSetupError"
    except ReleaseSetupError as exc:
        assert "already active" in str(exc)


def test_retention_prunes_old_releases_beyond_the_configured_count(db_session, monkeypatch):
    application, release_1, _ = _setup(db_session, replicas=1, retention=2)
    _gateway_mock(monkeypatch)
    _mock_commands(monkeypatch)
    monkeypatch.setattr(release_service, "DEFAULT_DRAIN_TIMEOUT_SECONDS", 0)

    from datetime import timedelta

    from app.db.models.application import Release
    from app.services import application_service

    # db_session runs the whole test in one outer transaction, so Postgres's
    # now() (transaction-start time, not statement time) would otherwise tie
    # every release's created_at — force a real, strictly increasing order
    # the way separate real-world deploys minutes apart naturally would.
    for i in range(3):  # 3 more successful switches on top of release_1 = 4 total
        config = application_service.config_from_application(application)
        deployment = release_service.start_new_release(
            db_session, application, config, actor_id=None
        )
        # Fix up created_at *before* the switch runs (and prunes) — pruning
        # happens as part of run_release_switch, so ordering must already be
        # correct by then, not patched up afterward.
        new_release = db_session.get(Release, deployment.release_id)
        new_release.created_at = release_1.created_at + timedelta(minutes=i + 1)
        db_session.commit()
        asyncio.run(release_service.run_release_switch(db_session, deployment.id, datetime.now(UTC)))

    remaining = (
        db_session.query(Release)
        .filter(Release.application_id == application.id, Release.status == ReleaseStatus.READY)
        .count()
    )
    assert remaining == 2  # retention_count=2, older ones pruned

    db_session.refresh(application)
    still_there = db_session.get(Release, application.active_release_id)
    assert still_there is not None  # the active release is never pruned
