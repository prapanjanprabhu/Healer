"""Phase 13: the Linux Docker adapter's control-plane side. Mocks
command_service.submit_command_and_wait the same way test_release_service.py
and test_self_healing_service.py do — the real Agent round trip (building/
pulling an image, creating/starting a container) is covered by the Go
agent's own dockerengine/dispatcher tests and by live verification. What
these tests exercise is the Control Plane's own adapter-branching logic:
payload shape, secret-to-env injection, and image_ref bookkeeping.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models.application import Instance, Release
from app.db.models.deployment import Deployment
from app.db.models.enums import AgentCommandType, AgentStatus, InstanceStatus, ReleaseStatus
from app.schemas.healer_yaml import HealerYamlV1
from app.services import application_service, deployment_service, release_service, secret_service
from app.services.deployment_service import (
    DeploymentSetupError,
    _build_deploy_release_payload,
    _build_start_instance_payload,
    _build_stop_instance_payload,
)
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


def _succeeded(result: dict) -> _FakeCommand:
    return _FakeCommand(status=_FakeCommandStatus("succeeded"), result=result)


def _docker_config(server_id, **overrides) -> dict:
    config = {
        "version": 1,
        "name": "Phase13 Docker App",
        "adapter": "linux-docker",
        "server_id": str(server_id),
        "source": {"type": "image", "location": "nginx@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        "linux": {"internal_port": 8000, "env": {"MODE": "prod"}},
        "health": {"path": "/health/"},
        "ports": {"start": 9200, "end": 9205},
        "replicas": {"min": 1, "max": 3},
        "secrets": [],
    }
    config.update(overrides)
    return config


def test_build_deploy_release_payload_for_linux_docker_has_no_windows_key(db_session):
    server = make_server(db_session)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = make_application(
        db_session, server_id=server.id, config=_docker_config(server.id)
    )
    release = make_release(db_session, application=application, ref="v1")

    payload = _build_deploy_release_payload(application, release, config)

    assert payload["adapter"] == "linux-docker"
    assert "windows" not in payload
    assert payload["linux"]["internal_port"] == 8000
    assert payload["source"]["location"] == "nginx@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_build_start_instance_payload_injects_secrets_as_env_vars(db_session):
    server = make_server(db_session)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = make_application(
        db_session, server_id=server.id, config=_docker_config(server.id)
    )
    release = make_release(db_session, application=application, ref="v1", image_ref="nginx@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        release_id=release.id,
        port=9200,
        status=InstanceStatus.STARTING,
        service_name="Healer-phase13-9200",
    )
    db_session.add(instance)
    db_session.flush()
    secret_service.set_secret(db_session, application.id, "API_KEY", "super-secret-value")

    payload = _build_start_instance_payload(db_session, release, instance, config)

    assert payload["adapter"] == "linux-docker"
    assert payload["port"] == 9200
    assert payload["linux"]["image_ref"] == "nginx@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert payload["linux"]["env"]["MODE"] == "prod"  # literal env from config
    assert payload["linux"]["env"]["API_KEY"] == "super-secret-value"  # injected secret


def test_build_stop_instance_payload_includes_the_adapter(db_session):
    server = make_server(db_session)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = make_application(
        db_session, server_id=server.id, config=_docker_config(server.id)
    )
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        port=9200,
        status=InstanceStatus.RUNNING,
        service_name="Healer-phase13-9200",
    )
    db_session.add(instance)
    db_session.flush()

    payload = _build_stop_instance_payload(instance, config)

    assert payload == {"adapter": "linux-docker", "service_name": "Healer-phase13-9200"}


def test_start_deployment_accepts_a_linux_docker_application(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = application_service.create_application(db_session, config)

    deployment = deployment_service.start_deployment(db_session, application, config, actor_id=None)

    assert deployment.application_id == application.id


def test_start_deployment_rejects_a_linux_docker_config_missing_its_linux_section(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = application_service.create_application(db_session, config)
    config.linux = None  # simulate a corrupted/partial config reaching start_deployment directly

    try:
        deployment_service.start_deployment(db_session, application, config, actor_id=None)
        assert False, "expected DeploymentSetupError"
    except DeploymentSetupError as exc:
        assert "linux" in str(exc)


def test_run_deployment_sets_image_ref_and_starts_a_container(db_session, monkeypatch):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = application_service.create_application(db_session, config)
    deployment = deployment_service.start_deployment(db_session, application, config, actor_id=None)

    sent = {"deploy_release": 0, "start_instance": 0}

    async def fake_submit(
        session, agent, command_type, payload, *, idempotency_key, ttl_seconds, wait_seconds
    ):
        if command_type == AgentCommandType.DEPLOY_RELEASE:
            sent["deploy_release"] += 1
            assert payload["adapter"] == "linux-docker"
            return _succeeded({"ok": True, "steps": [], "image_ref": "nginx@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
        if command_type == AgentCommandType.START_INSTANCE:
            sent["start_instance"] += 1
            assert payload["linux"]["image_ref"] == "nginx@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            return _succeeded({"ok": True, "steps": [], "container_id": "abc123"})
        raise AssertionError(f"unexpected command type {command_type}")

    monkeypatch.setattr(deployment_service.command_service, "submit_command_and_wait", fake_submit)

    asyncio.run(deployment_service.run_deployment(db_session, deployment.id, datetime.now(UTC)))

    release = db_session.get(Release, deployment.release_id)
    db_session.refresh(application)
    instance = db_session.scalars(select(Instance).where(Instance.release_id == release.id)).first()

    assert release.image_ref == "nginx@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert release.status == ReleaseStatus.READY
    assert application.active_release_id == release.id
    assert instance.status == InstanceStatus.RUNNING
    assert sent == {"deploy_release": 1, "start_instance": 1}


def test_start_rollback_rejects_a_linux_release_with_no_image_ref(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = application_service.create_application(db_session, config)
    active = make_release(db_session, application=application, ref="active", image_ref="nginx:1.24")
    application.active_release_id = active.id
    application.server_id = server.id
    application.port_range_start = 9200
    application.port_range_end = 9205
    db_session.commit()

    broken = make_release(
        db_session,
        application=application,
        ref="broken",
        status=ReleaseStatus.READY,
        image_ref=None,
    )

    try:
        release_service.start_rollback(db_session, application, broken.id, actor_id=None)
        assert False, "expected ReleaseSetupError"
    except ReleaseSetupError as exc:
        assert "not available to roll back to" in str(exc)


def test_start_rollback_accepts_a_linux_release_with_an_image_ref(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = application_service.create_application(db_session, config)
    active = make_release(db_session, application=application, ref="active", image_ref="nginx:1.24")
    application.active_release_id = active.id
    application.server_id = server.id
    application.port_range_start = 9200
    application.port_range_end = 9205
    db_session.commit()

    previous = make_release(
        db_session,
        application=application,
        ref="previous",
        status=ReleaseStatus.READY,
        image_ref="nginx:1.23",
    )

    deployment = release_service.start_rollback(db_session, application, previous.id, actor_id=None)

    assert deployment.release_id == previous.id
    assert deployment.kind == "rollback"


def test_retention_removes_only_unused_built_image_after_agent_success(db_session, monkeypatch):
    server = make_server(db_session)
    agent = make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = application_service.create_application(db_session, config)
    application.release_retention_count = 1
    old = make_release(
        db_session, application=application, ref="old", image_ref=f"healer-{application.slug}:old"
    )
    active = make_release(
        db_session, application=application, ref="active", image_ref=f"healer-{application.slug}:active"
    )
    old.created_at = active.created_at - timedelta(days=1)
    application.active_release_id = active.id
    deployment = Deployment(application_id=application.id, release_id=active.id, instance_count=1)
    db_session.add(deployment)
    db_session.commit()
    sent = []

    async def fake_submit(session, target_agent, command_type, payload, **kwargs):
        sent.append(payload)
        return _succeeded({"ok": True})

    monkeypatch.setattr(release_service.command_service, "submit_command_and_wait", fake_submit)
    asyncio.run(release_service._prune_old_releases(db_session, application, deployment, agent, config))

    assert sent == [{
        "operation": "cleanup_image", "adapter": "linux-docker",
        "app_slug": application.slug, "release_version": "old",
    }]
    assert db_session.get(Release, old.id) is None
    assert db_session.get(Release, active.id) is not None


def test_retention_keeps_release_when_image_cleanup_fails(db_session, monkeypatch):
    server = make_server(db_session)
    agent = make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_docker_config(server.id))
    application = application_service.create_application(db_session, config)
    application.release_retention_count = 1
    old = make_release(
        db_session, application=application, ref="old", image_ref=f"healer-{application.slug}:old"
    )
    active = make_release(db_session, application=application, ref="active", image_ref="another@sha256:" + "a" * 64)
    old.created_at = active.created_at - timedelta(days=1)
    application.active_release_id = active.id
    deployment = Deployment(application_id=application.id, release_id=active.id, instance_count=1)
    db_session.add(deployment)
    db_session.commit()

    async def fake_submit(session, target_agent, command_type, payload, **kwargs):
        return _succeeded({"ok": False})

    monkeypatch.setattr(release_service.command_service, "submit_command_and_wait", fake_submit)
    asyncio.run(release_service._prune_old_releases(db_session, application, deployment, agent, config))
    assert db_session.get(Release, old.id) is not None
