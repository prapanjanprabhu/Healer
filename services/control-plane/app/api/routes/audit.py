from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.audit import AuditLogEntryOut
from app.services import audit_service

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=list[AuditLogEntryOut])
def list_audit_log(
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    limit: int = Query(default=audit_service.DEFAULT_LIMIT, ge=1, le=audit_service.MAX_LIMIT),
    db: Session = Depends(get_db),
    # Administrator-only: the audit trail covers every user's activity,
    # not just the caller's own — not part of Operator's "view" grant.
    _current_user: CurrentUser = Depends(require_permission("view_audit")),
) -> list[AuditLogEntryOut]:
    entries = audit_service.list_entries(db, action=action, target_type=target_type, limit=limit)
    return [
        AuditLogEntryOut(
            id=e.id,
            actor_id=e.actor_id,
            actor_email=e.actor_email,
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            detail=e.detail,
            occurred_at=e.occurred_at,
        )
        for e in entries
    ]
