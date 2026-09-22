import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agent import Agent, AgentCommand, AgentCommandEvent
from app.db.models.enums import AgentCommandStatus, AgentCommandType
from app.repositories.agent_command_repository import AgentCommandRepository
from app.ws.connection_manager import connection_manager
from app.ws.protocol import make_envelope

DEFAULT_COMMAND_TTL_SECONDS = 120


def _command_envelope_payload(command: AgentCommand) -> dict:
    return {
        "command_id": str(command.id),
        "idempotency_key": command.idempotency_key,
        "type": command.command_type.value,
        "payload": command.payload,
        "created_at": command.created_at.isoformat(),
        "expires_at": command.expires_at.isoformat() if command.expires_at else None,
        "correlation_id": str(command.correlation_id) if command.correlation_id else None,
    }


async def submit_command(
    session: Session,
    agent: Agent,
    command_type: AgentCommandType,
    payload: dict,
    idempotency_key: str,
    *,
    correlation_id: uuid.UUID | None = None,
    ttl_seconds: int = DEFAULT_COMMAND_TTL_SECONDS,
) -> AgentCommand:
    """Idempotent: resubmitting the same idempotency_key returns the
    existing command rather than creating a duplicate (enforced by the
    unique constraint on agent_commands.idempotency_key, but checked first
    here to make the common case a clean no-op instead of a DB error).

    If the agent isn't currently connected, the command is created as
    PENDING and delivered later — see `deliver_pending_commands`, called
    when the agent (re)connects.
    """
    repo = AgentCommandRepository(session)
    existing = repo.get_by_idempotency_key(idempotency_key)
    if existing is not None:
        return existing

    now = datetime.now(UTC)
    command = AgentCommand(
        agent_id=agent.id,
        command_type=command_type,
        payload=payload,
        idempotency_key=idempotency_key,
        status=AgentCommandStatus.PENDING,
        correlation_id=correlation_id,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    session.add(command)
    session.flush()

    websocket = connection_manager.get(agent.id)
    if websocket is not None:
        await websocket.send_json(
            make_envelope("control.command", _command_envelope_payload(command))
        )
        repo.transition(command, AgentCommandStatus.SENT)

    return command


async def deliver_pending_commands(session: Session, agent: Agent) -> None:
    """Called right after an agent (re)connects — flushes any commands that
    were created while it was offline. This is what makes "reconnect" mean
    something more than just "shows as online again".
    """
    websocket = connection_manager.get(agent.id)
    if websocket is None:
        return

    repo = AgentCommandRepository(session)
    for command in repo.list_pending_for_agent(agent.id):
        await websocket.send_json(
            make_envelope("control.command", _command_envelope_payload(command))
        )
        repo.transition(command, AgentCommandStatus.SENT)


def record_event(
    session: Session,
    command: AgentCommand,
    status: AgentCommandStatus,
    *,
    result: dict | None = None,
    error: str | None = None,
    occurred_at: datetime,
) -> AgentCommand:
    repo = AgentCommandRepository(session)
    repo.transition(command, status)
    if result is not None:
        command.result = result
    if error is not None:
        command.error = error
    session.add(
        AgentCommandEvent(
            command_id=command.id,
            status=status,
            detail=(
                {"result": result} if result is not None else ({"error": error} if error else None)
            ),
            occurred_at=occurred_at,
        )
    )
    session.flush()
    return command


def expire_overdue_commands(session: Session, now: datetime) -> int:
    """Lazily sweep commands whose expires_at has passed with no terminal
    event. Called opportunistically from the command list/detail endpoints
    rather than on a schedule — no Celery beat is wired up yet (Phase 1).
    """
    overdue_statuses = (
        AgentCommandStatus.PENDING,
        AgentCommandStatus.SENT,
        AgentCommandStatus.ACKNOWLEDGED,
        AgentCommandStatus.RUNNING,
    )
    stmt = select(AgentCommand).where(
        AgentCommand.status.in_(overdue_statuses),
        AgentCommand.expires_at.is_not(None),
        AgentCommand.expires_at < now,
    )
    commands = session.scalars(stmt).all()
    repo = AgentCommandRepository(session)
    for command in commands:
        target = (
            AgentCommandStatus.EXPIRED
            if command.status == AgentCommandStatus.PENDING
            else AgentCommandStatus.TIMED_OUT
        )
        repo.transition(command, target)
        session.add(AgentCommandEvent(command_id=command.id, status=target, occurred_at=now))
    session.flush()
    return len(commands)
