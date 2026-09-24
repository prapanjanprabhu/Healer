import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog
from app.db.models.user import User

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


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


@dataclass
class AuditEntryView:
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_email: str | None
    action: str
    target_type: str
    target_id: str
    detail: dict | None
    occurred_at: datetime


def list_entries(
    session: Session,
    *,
    action: str | None = None,
    target_type: str | None = None,
    limit: int | None = None,
) -> list[AuditEntryView]:
    limit = limit or DEFAULT_LIMIT
    if limit <= 0 or limit > MAX_LIMIT:
        limit = DEFAULT_LIMIT

    stmt = select(AuditLog, User.email).join(User, User.id == AuditLog.actor_id, isouter=True)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    stmt = stmt.order_by(AuditLog.occurred_at.desc()).limit(limit)

    return [
        AuditEntryView(
            id=entry.id,
            actor_id=entry.actor_id,
            actor_email=actor_email,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            detail=entry.detail,
            occurred_at=entry.occurred_at,
        )
        for entry, actor_email in session.execute(stmt).all()
    ]
