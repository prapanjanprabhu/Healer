from datetime import datetime, timedelta

from app.db.models.agent import Agent
from app.db.models.enums import AgentStatus

# An agent heartbeats roughly every 15-30s (real agent, Phase 5); anything
# older than this is treated as offline even if the WebSocket close event
# never fired (network drop, killed process, etc).
OFFLINE_AFTER_SECONDS = 45


def is_online(agent: Agent, now: datetime) -> bool:
    """Online means: the connection lifecycle says CONNECTED *and* a
    heartbeat has actually been seen recently. Relying on `status` alone
    would report an agent as online forever if its process died without a
    clean WebSocket close.
    """
    if agent.status != AgentStatus.CONNECTED:
        return False
    if agent.last_seen_at is None:
        return False
    return now - agent.last_seen_at < timedelta(seconds=OFFLINE_AFTER_SECONDS)
