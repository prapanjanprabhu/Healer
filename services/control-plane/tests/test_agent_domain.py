import uuid
from datetime import UTC, datetime, timedelta

from app.db.models.agent import Agent
from app.db.models.enums import AgentStatus
from app.domain.agent_status import OFFLINE_AFTER_SECONDS, is_online


def _agent(*, status: AgentStatus, last_seen_at: datetime | None) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        server_id=uuid.uuid4(),
        agent_version="0.1.0-test",
        status=status,
        last_seen_at=last_seen_at,
    )


def test_disconnected_agent_is_never_online():
    now = datetime.now(UTC)
    agent = _agent(status=AgentStatus.DISCONNECTED, last_seen_at=now)
    assert is_online(agent, now) is False


def test_connected_agent_with_no_heartbeat_yet_is_not_online():
    now = datetime.now(UTC)
    agent = _agent(status=AgentStatus.CONNECTED, last_seen_at=None)
    assert is_online(agent, now) is False


def test_connected_agent_with_recent_heartbeat_is_online():
    now = datetime.now(UTC)
    agent = _agent(status=AgentStatus.CONNECTED, last_seen_at=now - timedelta(seconds=5))
    assert is_online(agent, now) is True


def test_connected_agent_with_stale_heartbeat_is_offline():
    """Covers the case a clean WebSocket close never happens (killed
    process, network drop) — status alone would say CONNECTED forever.
    """
    now = datetime.now(UTC)
    stale = now - timedelta(seconds=OFFLINE_AFTER_SECONDS + 30)
    agent = _agent(status=AgentStatus.CONNECTED, last_seen_at=stale)
    assert is_online(agent, now) is False
