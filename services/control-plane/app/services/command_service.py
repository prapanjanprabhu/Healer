import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agent import Agent, AgentCommand, AgentCommandEvent
from app.db.models.enums import AgentCommandStatus, AgentCommandType
from app.repositories.agent_command_repository import AgentCommandRepository
from app.ws.connection_manager import connection_manager
from app.ws.protocol import make_envelope

DEFAULT_COMMAND_TTL_SECONDS = 120

TERMINAL_STATUSES = frozenset(
    {AgentCommandStatus.SUCCEEDED, AgentCommandStatus.FAILED, AgentCommandStatus.TIMED_OUT}
)

# Cross-task signaling within this single control-plane process: the
# WebSocket route (app/api/routes/ws.py) receives the terminal
# agent.command_event on its own asyncio task and calls record_event; an API
# request waiting on the same command_id (e.g. POST /applications/{id}/validate)
# is a *different* task in the *same* event loop. An asyncio.Event is exactly
# what coordinates that — see docs/agent-protocol.md's note on why this only
# works for a single control-plane instance (V1's whole deployment model).
_waiters: dict[uuid.UUID, asyncio.Event] = {}


def _register_waiter(command_id: uuid.UUID) -> asyncio.Event:
    event = asyncio.Event()
    _waiters[command_id] = event
    return event


def _signal_waiter(command_id: uuid.UUID) -> None:
    event = _waiters.get(command_id)
    if event is not None:
        event.set()


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
    _before_send: Callable[[AgentCommand], None] | None = None,
) -> AgentCommand:
    """Idempotent: resubmitting the same idempotency_key returns the
    existing command rather than creating a duplicate (enforced by the
    unique constraint on agent_commands.idempotency_key, but checked first
    here to make the common case a clean no-op instead of a DB error).

    If the agent isn't currently connected, the command is created as
    PENDING and delivered later — see `deliver_pending_commands`, called
    when the agent (re)connects.

    `_before_send` runs after the command is committed but before the
    WebSocket send (whose `await` yields control to the event loop, letting
    the WS route's receive task run first if the agent replies fast enough).
    `submit_command_and_wait` uses it to register its waiter before that
    gap can open, so an instant reply is never missed.

    The commit right after creating the row is a deliberate, narrow
    exception to "services only flush, get_db commits" (see app/db/session.py):
    the row must be visible to *other* sessions — namely the WebSocket
    route's, handling the agent's reply on its own connection — before the
    agent is told the command exists. A fast agent can reply within
    milliseconds, well before this request's transaction would otherwise
    commit at request teardown; without this commit the WS route's
    `db.get(AgentCommand, ...)` finds nothing and the reply is silently
    dropped (found the hard way: a real agent on the same machine replying
    over loopback consistently won this race).
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
    session.commit()

    if _before_send is not None:
        _before_send(command)

    websocket = connection_manager.get(agent.id)
    if websocket is not None:
        await websocket.send_json(
            make_envelope("control.command", _command_envelope_payload(command))
        )
        repo.transition(command, AgentCommandStatus.SENT)
        session.commit()

    return command


async def submit_command_and_wait(
    session: Session,
    agent: Agent,
    command_type: AgentCommandType,
    payload: dict,
    idempotency_key: str,
    *,
    correlation_id: uuid.UUID | None = None,
    ttl_seconds: int = DEFAULT_COMMAND_TTL_SECONDS,
    wait_seconds: float = 15.0,
) -> AgentCommand:
    """Like submit_command, but waits (up to wait_seconds) for a terminal
    result before returning — for API endpoints that want to hand the
    caller a finished answer (e.g. application validation) rather than
    make the dashboard poll. If the wait times out, the command is left
    exactly as submit_command would have left it (sent/pending) and the
    caller sees whatever status it's in — this never blocks forever.
    """
    registered: dict[str, asyncio.Event] = {}

    def _register_before_send(command: AgentCommand) -> None:
        registered["event"] = _register_waiter(command.id)

    command = await submit_command(
        session,
        agent,
        command_type,
        payload,
        idempotency_key,
        correlation_id=correlation_id,
        ttl_seconds=ttl_seconds,
        _before_send=_register_before_send,
    )

    if command.status in TERMINAL_STATUSES:
        _waiters.pop(command.id, None)
        return command

    # An idempotency hit returns an existing command without going through
    # _before_send, so it may not have a waiter registered yet.
    event = registered.get("event") or _register_waiter(command.id)
    try:
        await asyncio.wait_for(event.wait(), timeout=wait_seconds)
    except TimeoutError:
        pass
    finally:
        _waiters.pop(command.id, None)

    # The terminal update was committed by a *different* session (the
    # WebSocket route's) — expire this row so the next read goes back to
    # the database rather than returning stale, already-loaded attributes.
    session.expire(command)
    return AgentCommandRepository(session).get(command.id)


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

    if status in TERMINAL_STATUSES:
        _signal_waiter(command.id)

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
