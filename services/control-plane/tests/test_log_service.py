"""Unit-level tests for log_service. command_service.submit_command_and_wait
is mocked (same rationale as test_release_service.py / test_self_healing_service.py)
— the real Agent round trip for collect_logs is covered by the Go agent's own
tests and by live verification; what this exercises is log_service's own
orchestration: source discovery, error handling when the agent/release
isn't ready, and that secret values get redacted before returning.
"""

import asyncio
from dataclasses import dataclass, field

import pytest

from app.db.models.application import Instance
from app.db.models.enums import AdapterType, AgentStatus, InstanceStatus
from app.services import log_service, secret_service
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


def _mock_submit(monkeypatch, fake_command_or_factory):
    async def fake_submit(session, agent, command_type, payload, idempotency_key, **kwargs):
        if callable(fake_command_or_factory):
            return fake_command_or_factory(payload)
        return fake_command_or_factory

    monkeypatch.setattr(log_service.command_service, "submit_command_and_wait", fake_submit)


def _setup(
    session,
    *,
    agent_status=AgentStatus.CONNECTED,
    release_dir="C:\\ProgramData\\Healer\\apps\\logtest\\releases\\v1",
):
    server = make_server(session)
    make_agent(session, server=server, status=agent_status)
    application = make_application(session, server_id=server.id, adapter_type=AdapterType.WINDOWS_WAITRESS_SERVICE)
    release = release_dir and make_release(
        session, application=application, release_dir=release_dir
    )
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        release_id=release.id if release else None,
        port=9034,
        status=InstanceStatus.RUNNING,
        service_name=f"Healer-{application.slug}-9034",
    )
    session.add(instance)
    session.flush()
    return application, instance


def test_list_log_sources_has_stdout_stderr_per_instance_and_a_deployment_entry(db_session):
    application, instance = _setup(db_session)

    sources = log_service.list_log_sources(db_session, application.id)

    types = {s.type for s in sources}
    assert types == {"stdout", "stderr", "deployment"}
    stdout_sources = [s for s in sources if s.type == "stdout"]
    assert len(stdout_sources) == 1
    assert stdout_sources[0].instance_id == instance.id


def test_fetch_instance_log_returns_redacted_lines(db_session, monkeypatch):
    application, instance = _setup(db_session)
    secret_service.set_secret(db_session, application.id, "API_KEY", "sk-verysecretvalue")
    _mock_submit(
        monkeypatch,
        _succeeded(
            {
                "ok": True,
                "not_found": False,
                "lines": ["normal log line", "using key sk-verysecretvalue for upstream"],
                "size": 100,
                "end_offset": 100,
                "truncated": False,
            }
        ),
    )

    chunk = asyncio.run(log_service.fetch_instance_log(db_session, instance, "stdout"))

    assert chunk["lines"][0] == "normal log line"
    assert "sk-verysecretvalue" not in chunk["lines"][1]
    assert chunk["end_offset"] == 100


def test_fetch_instance_log_raises_when_agent_not_connected(db_session, monkeypatch):
    application, instance = _setup(db_session, agent_status=AgentStatus.DISCONNECTED)

    with pytest.raises(log_service.LogUnavailableError):
        asyncio.run(log_service.fetch_instance_log(db_session, instance, "stdout"))


def test_fetch_instance_log_raises_when_release_dir_unknown(db_session, monkeypatch):
    application, instance = _setup(db_session, release_dir=None)

    with pytest.raises(log_service.LogUnavailableError):
        asyncio.run(log_service.fetch_instance_log(db_session, instance, "stdout"))


def test_fetch_instance_log_raises_when_agent_command_fails(db_session, monkeypatch):
    application, instance = _setup(db_session)
    _mock_submit(monkeypatch, _FakeCommand(status=_FakeCommandStatus("failed"), error="boom"))

    with pytest.raises(log_service.LogUnavailableError, match="boom"):
        asyncio.run(log_service.fetch_instance_log(db_session, instance, "stdout"))


def test_fetch_instance_log_passes_clamped_limits_to_the_agent(db_session, monkeypatch):
    application, instance = _setup(db_session)
    captured = {}

    async def fake_submit(session, agent, command_type, payload, idempotency_key, **kwargs):
        captured.update(payload)
        return _succeeded(
            {"lines": [], "size": 0, "end_offset": 0, "truncated": False, "not_found": False}
        )

    monkeypatch.setattr(log_service.command_service, "submit_command_and_wait", fake_submit)

    asyncio.run(
        log_service.fetch_instance_log(
            db_session, instance, "stderr", max_bytes=100 * 1024 * 1024, max_lines=10_000_000
        )
    )

    assert captured["max_bytes"] == log_service.DEFAULT_MAX_BYTES
    assert captured["max_lines"] == log_service.DEFAULT_MAX_LINES
    assert captured["stream"] == "stderr"


def test_linux_container_logs_use_adapter_without_a_release_directory(db_session, monkeypatch):
    application, instance = _setup(db_session)
    application.adapter_type = AdapterType.LINUX_DOCKER
    release = db_session.get(log_service.Release, instance.release_id)
    release.release_dir = None
    release.image_ref = "example@sha256:" + "a" * 64
    captured = {}

    async def fake_submit(session, agent, command_type, payload, idempotency_key, **kwargs):
        captured.update(payload)
        return _succeeded({"lines": ["secret=test-secret-value"], "size": 24, "end_offset": 24})

    secret_service.set_secret(db_session, application.id, "TOKEN", "test-secret-value")
    monkeypatch.setattr(log_service.command_service, "submit_command_and_wait", fake_submit)
    chunk = asyncio.run(log_service.fetch_instance_log(db_session, instance, "stdout"))
    assert captured["adapter"] == "linux-docker"
    assert "log_dir" not in captured
    assert "test-secret-value" not in chunk["lines"][0]
