import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog


def record(
    session: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict | None = None,
) -> AuditLog:
    """Write one audit log entry.

    `detail` must never contain a password, token, private key, or secret
    value — callers pass only non-sensitive context (e.g. a failure reason).
    """
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        occurred_at=datetime.now(UTC),
    )
    session.add(entry)
    session.flush()
    return entry
