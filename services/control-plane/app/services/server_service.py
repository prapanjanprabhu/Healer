from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import generate_token, hash_token
from app.db.models.agent import Agent
from app.db.models.enums import AgentStatus, ServerOS, ServerStatus
from app.db.models.server import EnrollmentToken, Server
from app.ws.connection_manager import connection_manager

DEFAULT_ENROLLMENT_TOKEN_TTL_MINUTES = 60


def create_server(session: Session, *, name: str, hostname: str, os: ServerOS) -> Server:
    server = Server(name=name, hostname=hostname, os=os, status=ServerStatus.PENDING)
    session.add(server)
    session.flush()
    return server


def issue_enrollment_token(
    session: Session, server: Server, ttl_minutes: int = DEFAULT_ENROLLMENT_TOKEN_TTL_MINUTES
) -> tuple[str, EnrollmentToken]:
    """Returns the raw token exactly once — only its hash is persisted."""
    raw_token = generate_token()
    row = EnrollmentToken(
        server_id=server.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
    )
    session.add(row)
    session.flush()
    return raw_token, row


def revoke_enrollment_token(session: Session, token: EnrollmentToken) -> None:
    if token.used_at is None and token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        session.flush()


async def revoke_agent(session: Session, agent: Agent) -> None:
    """Force-disconnects an already-enrolled Agent and invalidates its
    credential — the gap this project's Phase 15 audit flagged: revocation
    previously existed only for a pre-enrollment EnrollmentToken, with no
    way at all to cut off a server that had already completed enrollment
    (e.g. decommissioned, or a suspected-compromised credential). A revoked
    agent's next reconnect attempt fails at authentication
    (`AgentRepository.get_by_credential_hash` finds nothing); re-enrolling
    it (a fresh enrollment token) works exactly like first-time enrollment,
    since `agent_service.enroll_agent` already handles rotating an existing
    Agent row's credential.
    """
    agent.credential_hash = None
    agent.status = AgentStatus.DISCONNECTED
    session.commit()

    websocket = connection_manager.get(agent.id)
    if websocket is not None:
        await websocket.close(code=4001, reason="agent credential revoked")
        await connection_manager.unregister(agent.id)
