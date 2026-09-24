import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission
from app.db.session import get_db
from app.repositories.server_repository import ServerRepository
from app.schemas.metrics import MetricsSnapshotOut
from app.services import metrics_service

router = APIRouter(prefix="/servers", tags=["metrics"])


@router.get("/{server_id}/metrics", response_model=list[MetricsSnapshotOut])
def list_metrics(
    server_id: uuid.UUID,
    hours: int = Query(default=metrics_service.DEFAULT_HOURS, ge=1),
    limit: int = Query(default=metrics_service.DEFAULT_LIMIT, ge=1),
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> list[MetricsSnapshotOut]:
    """Recent CPU/RAM/disk snapshots for one server, oldest first — the
    dashboard's summary cards and sparkline charts. Bounded by
    metrics_service's own hard caps regardless of what's requested here.
    """
    if ServerRepository(db).get(server_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="server not found")
    rows = metrics_service.get_recent_metrics(db, server_id, hours=hours, limit=limit)
    return [
        MetricsSnapshotOut(
            server_id=r.server_id,
            cpu_percent=float(r.cpu_percent),
            memory_percent=float(r.memory_percent),
            disk_percent=float(r.disk_percent),
            recorded_at=r.recorded_at,
        )
        for r in rows
    ]
