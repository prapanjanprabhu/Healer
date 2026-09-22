"""Python-side mirror of the JSON message contract in protocols/v1.

The JSON Schemas under protocols/v1 remain the source of truth for the wire
format; these are the runtime validation/construction helpers used by the
Control Plane.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "1.0"


def make_envelope(message_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": str(uuid.uuid4()),
        "type": message_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


class AgentHelloPayload(BaseModel):
    """Sent once, immediately after the WebSocket connects — the capability
    report. See protocols/v1/agent-hello.schema.json.
    """

    agent_version: str
    os: Literal["windows", "linux"]
    arch: Literal["amd64", "arm64"]
    adapters: list[str] = Field(default_factory=list)


class AgentHeartbeatPayload(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    disk_percent: float = Field(ge=0, le=100)
    instances: list[dict[str, Any]] = Field(default_factory=list)


class AgentCommandEventPayload(BaseModel):
    command_id: uuid.UUID
    status: Literal["acknowledged", "running", "succeeded", "failed", "timed_out"]
    result: dict[str, Any] | None = None
    error: str | None = None
    occurred_at: datetime
