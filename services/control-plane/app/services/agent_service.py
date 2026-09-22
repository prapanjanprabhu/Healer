from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.security import generate_token, hash_token
from app.db.models.agent import Agent
from app.db.models.enums import AgentStatus
from app.db.models.metrics import MetricsSnapshot
from app.repositories.agent_repository import AgentRepository
from app.repositories.enrollment_token_repository import EnrollmentTokenRepository
from app.ws.protocol import AgentHeartbeatPayload, AgentHelloPayload


class EnrollmentError(Exception):
    """Stable code (e.g. "token_expired") — never echoes the raw token."""


def enroll_agent(session: Session, raw_token: str) -> tuple[Agent, str]:
    """Consume a single-use enrollment token and issue a long-lived agent
    credential. Re-enrolling a server that already has an Agent row rotates
    its credential (invalidating the old one) rather than creating a
    duplicate agent — a server has exactly one Agent identity.
    """
    token_repo = EnrollmentTokenRepository(session)
    token = token_repo.get_by_token_hash(hash_token(raw_token))
    if token is None:
        raise EnrollmentError("invalid_token")

    now = datetime.now(UTC)
    if token.revoked_at is not None:
        raise EnrollmentError("token_revoked")
    if token.used_at is not None:
        raise EnrollmentError("token_already_used")
    if token.expires_at < now:
        raise EnrollmentError("token_expired")

    token.used_at = now

    agent_repo = AgentRepository(session)
    agent = agent_repo.get_by_server_id(token.server_id)
    raw_credential = generate_token()
    if agent is None:
        agent = Agent(
            server_id=token.server_id,
            agent_version="unknown",
            status=AgentStatus.DISCONNECTED,
            credential_hash=hash_token(raw_credential),
        )
        session.add(agent)
    else:
        agent.credential_hash = hash_token(raw_credential)
    session.flush()
    return agent, raw_credential


def authenticate_agent_credential(session: Session, raw_credential: str) -> Agent | None:
    return AgentRepository(session).get_by_credential_hash(hash_token(raw_credential))


def apply_hello(session: Session, agent: Agent, payload: dict) -> None:
    hello = AgentHelloPayload.model_validate(payload)
    agent.agent_version = hello.agent_version
    agent.capabilities = {"os": hello.os, "arch": hello.arch, "adapters": hello.adapters}
    session.flush()


def apply_heartbeat(session: Session, agent: Agent, payload: dict) -> None:
    heartbeat = AgentHeartbeatPayload.model_validate(payload)
    now = datetime.now(UTC)
    agent.last_seen_at = now
    session.add(
        MetricsSnapshot(
            server_id=agent.server_id,
            cpu_percent=heartbeat.cpu_percent,
            memory_percent=heartbeat.memory_percent,
            disk_percent=heartbeat.disk_percent,
            recorded_at=now,
        )
    )
    session.flush()
