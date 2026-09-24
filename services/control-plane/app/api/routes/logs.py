import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission
from app.db.models.application import Instance
from app.db.session import get_db
from app.repositories.application_repository import ApplicationRepository
from app.schemas.logs import LogChunkOut, LogSourceOut
from app.services import log_service

router = APIRouter(prefix="/applications", tags=["logs"])


def _get_instance(db: Session, application_id: uuid.UUID, instance_id: uuid.UUID) -> Instance:
    instance = db.scalars(
        select(Instance).where(
            Instance.id == instance_id, Instance.application_id == application_id
        )
    ).first()
    if instance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="instance not found")
    return instance


@router.get("/{application_id}/log-sources", response_model=list[LogSourceOut])
def list_log_sources(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> list[LogSourceOut]:
    if ApplicationRepository(db).get(application_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")
    return [LogSourceOut(**vars(s)) for s in log_service.list_log_sources(db, application_id)]


@router.get("/{application_id}/instances/{instance_id}/logs", response_model=LogChunkOut)
async def get_instance_log(
    application_id: uuid.UUID,
    instance_id: uuid.UUID,
    stream: str = Query(pattern="^(stdout|stderr)$"),
    max_bytes: int | None = Query(default=None, ge=1),
    max_lines: int | None = Query(default=None, ge=1),
    offset: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> LogChunkOut:
    """A single bounded, redacted read of one instance's stdout/stderr —
    the dashboard's initial log view before switching to the live stream.
    """
    instance = _get_instance(db, application_id, instance_id)
    try:
        chunk = await log_service.fetch_instance_log(
            db, instance, stream, max_bytes=max_bytes, max_lines=max_lines, offset=offset
        )
    except log_service.LogUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return LogChunkOut(**chunk)


@router.get("/{application_id}/instances/{instance_id}/logs/stream")
async def stream_instance_log(
    application_id: uuid.UUID,
    instance_id: uuid.UUID,
    stream: str = Query(pattern="^(stdout|stderr)$"),
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> StreamingResponse:
    """Live tail over Server-Sent Events: an initial bounded recent view,
    then only newly-appended, redacted lines every couple of seconds, for a
    bounded duration (the dashboard reconnects to continue). See
    log_service.stream_instance_log.
    """
    _get_instance(db, application_id, instance_id)

    async def event_source():
        async for event in log_service.stream_instance_log(application_id, instance_id, stream):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
