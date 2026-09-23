import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, verify_csrf
from app.db.models.notification import Notification
from app.db.session import get_db
from app.schemas.notifications import NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[NotificationOut]:
    """Every notification addressed to this administrator, plus every
    unscoped (broadcast) one — e.g. self-healing giving up on an instance.
    Any authenticated user may read these (there's no separate "notify"
    permission — seeing your own alerts isn't a privileged action).
    """
    notifications = db.scalars(
        select(Notification)
        .where(or_(Notification.user_id == current_user.id, Notification.user_id.is_(None)))
        .order_by(Notification.created_at.desc())
        .limit(100)
    ).all()
    return [
        NotificationOut(
            id=n.id,
            notification_type=n.notification_type,
            message=n.message,
            read_at=n.read_at,
            created_at=n.created_at,
        )
        for n in notifications
    ]


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notification_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> None:
    notification = db.get(Notification, notification_id)
    if notification is None or (
        notification.user_id is not None and notification.user_id != current_user.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="notification not found")
    notification.read_at = datetime.now(UTC)
