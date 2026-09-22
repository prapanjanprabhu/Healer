import asyncio
import uuid

from fastapi import WebSocket


class ConnectionManager:
    """In-memory registry of live agent WebSocket connections for this
    single Control Plane process.

    V1 runs exactly one control-plane instance — a multi-instance
    deployment would need a shared registry (e.g. Redis pub/sub) to route a
    command to whichever instance holds that agent's socket. Out of scope
    for V1; noted here so it isn't a silent landmine later.
    """

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, agent_id: uuid.UUID, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[agent_id] = websocket

    async def unregister(self, agent_id: uuid.UUID) -> None:
        async with self._lock:
            self._connections.pop(agent_id, None)

    def get(self, agent_id: uuid.UUID) -> WebSocket | None:
        return self._connections.get(agent_id)

    def is_connected(self, agent_id: uuid.UUID) -> bool:
        return agent_id in self._connections


connection_manager = ConnectionManager()
