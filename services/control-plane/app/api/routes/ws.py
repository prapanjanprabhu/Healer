import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.db.models.agent import Agent, AgentCommand, AgentConnection
from app.db.models.enums import AgentCommandStatus, AgentStatus
from app.db.session import get_db
from app.repositories.agent_repository import AgentRepository
from app.services import agent_service, command_service
from app.ws.connection_manager import connection_manager

router = APIRouter()


@router.websocket("/ws/agent")
async def agent_socket(websocket: WebSocket, db: Session = Depends(get_db)) -> None:
    """The Agent's single outbound connection. Authenticated with the
    long-lived credential issued at enrollment (POST /agents/enroll),
    presented as `Authorization: Bearer <credential>` on the upgrade
    request — never the enrollment token itself, which is single-use and
    already consumed by then. See docs/agent-protocol.md.
    """
    auth_header = websocket.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    raw_credential = auth_header[len("bearer ") :].strip()

    agent = AgentRepository(db).get_by_credential_hash(hash_token(raw_credential))
    if agent is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    await connection_manager.register(agent.id, websocket)

    now = datetime.now(UTC)
    agent.status = AgentStatus.CONNECTED
    agent.last_seen_at = now
    db.add(
        AgentConnection(
            agent_id=agent.id,
            connected_at=now,
            remote_addr=websocket.client.host if websocket.client else None,
        )
    )
    db.commit()

    await command_service.deliver_pending_commands(db, agent)
    db.commit()

    try:
        while True:
            message = await websocket.receive_json()
            await _handle_message(db, agent, message)
            db.commit()
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.unregister(agent.id)
        agent_row = db.get(Agent, agent.id)
        if agent_row is not None:
            agent_row.status = AgentStatus.DISCONNECTED
        open_connection = (
            db.query(AgentConnection)
            .filter(AgentConnection.agent_id == agent.id, AgentConnection.disconnected_at.is_(None))
            .order_by(AgentConnection.connected_at.desc())
            .first()
        )
        if open_connection is not None:
            open_connection.disconnected_at = datetime.now(UTC)
        db.commit()


async def _handle_message(db: Session, agent: Agent, message: dict) -> None:
    message_type = message.get("type")
    payload = message.get("payload", {})

    if message_type == "agent.hello":
        agent_service.apply_hello(db, agent, payload)
    elif message_type == "agent.heartbeat":
        agent_service.apply_heartbeat(db, agent, payload)
    elif message_type == "agent.command_event":
        await _handle_command_event(db, agent, payload)
    # Unknown message types are ignored, not fatal — forward compatibility
    # for future protocol versions (see protocols/README.md versioning rules).


async def _handle_command_event(db: Session, agent: Agent, payload: dict) -> None:
    command_id_raw = payload.get("command_id")
    if not command_id_raw:
        return
    try:
        command_id = uuid.UUID(command_id_raw)
    except ValueError:
        return

    command = db.get(AgentCommand, command_id)
    if command is None or command.agent_id != agent.id:
        # Never let one agent update a command that isn't its own.
        return

    status_value = payload.get("status")
    try:
        new_status = AgentCommandStatus(status_value) if status_value else None
    except ValueError:
        new_status = None
    if new_status is None:
        return

    occurred_at_raw = payload.get("occurred_at")
    occurred_at = datetime.fromisoformat(occurred_at_raw) if occurred_at_raw else datetime.now(UTC)

    command_service.record_event(
        db,
        command,
        new_status,
        result=payload.get("result"),
        error=payload.get("error"),
        occurred_at=occurred_at,
    )
