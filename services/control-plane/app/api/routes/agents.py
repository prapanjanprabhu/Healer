import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require_permission, verify_csrf
from app.core.config import settings
from app.db.models.agent import Agent, AgentCommand
from app.db.session import get_db
from app.domain.command_permissions import permission_for
from app.domain.permissions import has_permission
from app.repositories.agent_command_repository import AgentCommandRepository
from app.schemas.agents import AgentEnrollRequest, AgentEnrollResponse
from app.schemas.commands import CommandOut, CommandSubmitRequest
from app.services import agent_service, audit_service, command_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/enroll", response_model=AgentEnrollResponse)
def enroll(payload: AgentEnrollRequest, db: Session = Depends(get_db)) -> AgentEnrollResponse:
    """No human auth here — the single-use enrollment token itself is the
    credential authorizing this call, the same way a password authorizes
    /auth/login. See docs/agent-protocol.md.
    """
    try:
        agent, raw_credential = agent_service.enroll_agent(db, payload.token)
    except agent_service.EnrollmentError as exc:
        audit_service.record(
            db,
            actor_id=None,
            action="agent.enroll_failed",
            target_type="enrollment_token",
            target_id="unknown",
            detail={"reason": str(exc)},
        )
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid, expired, already-used, or revoked enrollment token",
        )

    audit_service.record(
        db,
        actor_id=None,
        action="agent.enrolled",
        target_type="agent",
        target_id=str(agent.id),
        detail={"server_id": str(agent.server_id)},
    )
    return AgentEnrollResponse(
        agent_id=agent.id,
        server_id=agent.server_id,
        credential=raw_credential,
        control_plane_ws_url=settings.agent_ws_public_url,
    )


@router.get("/{agent_id}/commands", response_model=list[CommandOut])
def list_commands(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> list[CommandOut]:
    command_service.expire_overdue_commands(db, datetime.now(UTC))
    return [CommandOut.from_model(c) for c in AgentCommandRepository(db).list_by_agent(agent_id)]


@router.get("/{agent_id}/commands/{command_id}", response_model=CommandOut)
def get_command(
    agent_id: uuid.UUID,
    command_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> CommandOut:
    command_service.expire_overdue_commands(db, datetime.now(UTC))
    command = db.get(AgentCommand, command_id)
    if command is None or command.agent_id != agent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="command not found")
    return CommandOut.from_model(command)


@router.post("/{agent_id}/commands", response_model=CommandOut, status_code=status.HTTP_201_CREATED)
async def create_command(
    agent_id: uuid.UUID,
    payload: CommandSubmitRequest,
    db: Session = Depends(get_db),
    # Auth resolved before CSRF (see docs/auth.md) so an unauthenticated
    # request gets 401, not a misleading 403 CSRF mismatch.
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> CommandOut:
    required_permission = permission_for(payload.type)
    if not has_permission(set(current_user.roles), required_permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="insufficient permissions")

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="agent not found")

    command = await command_service.submit_command(
        db,
        agent,
        payload.type,
        payload.payload,
        payload.idempotency_key,
        correlation_id=payload.correlation_id,
        ttl_seconds=payload.ttl_seconds,
    )

    audit_service.record(
        db,
        actor_id=current_user.id,
        action="agent.command_submitted",
        target_type="agent_command",
        target_id=str(command.id),
        detail={"type": payload.type.value, "agent_id": str(agent_id)},
    )
    return CommandOut.from_model(command)
