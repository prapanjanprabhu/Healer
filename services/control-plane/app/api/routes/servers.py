import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission, verify_csrf
from app.db.session import get_db
from app.domain.agent_status import is_online
from app.repositories.agent_repository import AgentRepository
from app.repositories.enrollment_token_repository import EnrollmentTokenRepository
from app.repositories.server_repository import ServerRepository
from app.schemas.servers import (
    EnrollmentTokenIssuedOut,
    EnrollmentTokenOut,
    ServerCreateRequest,
    ServerOut,
)
from app.services import audit_service, server_service

router = APIRouter(prefix="/servers", tags=["servers"])


def _server_out(db: Session, server) -> ServerOut:
    agent = AgentRepository(db).get_by_server_id(server.id)
    now = datetime.now(UTC)
    return ServerOut(
        id=server.id,
        name=server.name,
        hostname=server.hostname,
        os=server.os,
        status=server.status,
        online=is_online(agent, now) if agent else False,
        agent_version=agent.agent_version if agent else None,
        last_seen_at=agent.last_seen_at if agent else None,
        created_at=server.created_at,
    )


@router.get("", response_model=list[ServerOut])
def list_servers(
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> list[ServerOut]:
    return [_server_out(db, server) for server in ServerRepository(db).list(limit=500)]


@router.get("/{server_id}", response_model=ServerOut)
def get_server(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> ServerOut:
    server = ServerRepository(db).get(server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="server not found")
    return _server_out(db, server)


@router.post("", response_model=ServerOut, status_code=status.HTTP_201_CREATED)
def create_server(
    payload: ServerCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_servers")),
    _csrf: None = Depends(verify_csrf),
) -> ServerOut:
    if ServerRepository(db).get_by_hostname(payload.hostname) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="hostname already registered")

    server = server_service.create_server(
        db, name=payload.name, hostname=payload.hostname, os=payload.os
    )
    audit_service.record(
        db,
        actor_id=current_user.id,
        action="server.create",
        target_type="server",
        target_id=str(server.id),
        detail={"hostname": server.hostname, "os": server.os.value},
    )
    return _server_out(db, server)


@router.post(
    "/{server_id}/enrollment-tokens",
    response_model=EnrollmentTokenIssuedOut,
    status_code=status.HTTP_201_CREATED,
)
def create_enrollment_token(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_servers")),
    _csrf: None = Depends(verify_csrf),
) -> EnrollmentTokenIssuedOut:
    server = ServerRepository(db).get(server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="server not found")

    raw_token, token_row = server_service.issue_enrollment_token(db, server)
    audit_service.record(
        db,
        actor_id=current_user.id,
        action="server.enrollment_token_issued",
        target_type="server",
        target_id=str(server.id),
        detail={"enrollment_token_id": str(token_row.id)},
    )
    return EnrollmentTokenIssuedOut(
        id=token_row.id, token=raw_token, expires_at=token_row.expires_at
    )


@router.get("/{server_id}/enrollment-tokens", response_model=list[EnrollmentTokenOut])
def list_enrollment_tokens(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("manage_servers")),
) -> list[EnrollmentTokenOut]:
    tokens = EnrollmentTokenRepository(db).list_by_server(server_id)
    return [
        EnrollmentTokenOut(
            id=t.id,
            expires_at=t.expires_at,
            used_at=t.used_at,
            revoked_at=t.revoked_at,
            created_at=t.created_at,
        )
        for t in tokens
    ]


@router.delete("/{server_id}/enrollment-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_enrollment_token(
    server_id: uuid.UUID,
    token_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_servers")),
    _csrf: None = Depends(verify_csrf),
) -> Response:
    token = EnrollmentTokenRepository(db).get(token_id)
    if token is None or token.server_id != server_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="enrollment token not found")

    server_service.revoke_enrollment_token(db, token)
    audit_service.record(
        db,
        actor_id=current_user.id,
        action="server.enrollment_token_revoked",
        target_type="enrollment_token",
        target_id=str(token.id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{server_id}/agent/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_agent(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("manage_servers")),
    _csrf: None = Depends(verify_csrf),
) -> Response:
    """Force-disconnects this server's Agent (if connected) and invalidates
    its credential — for a decommissioned server or a suspected-compromised
    credential. Re-enrolling it (a fresh enrollment token) works exactly
    like first-time enrollment. See app/services/server_service.py.
    """
    agent = AgentRepository(db).get_by_server_id(server_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no agent enrolled for this server")

    await server_service.revoke_agent(db, agent)
    audit_service.record(
        db,
        actor_id=current_user.id,
        action="server.agent_revoked",
        target_type="server",
        target_id=str(server_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
