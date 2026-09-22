from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import generate_token, hash_token
from app.db.models.enums import ServerOS, ServerStatus
from app.db.models.server import EnrollmentToken, Server

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
