import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from app.db.models.agent import AgentCommand
from app.db.models.enums import AgentCommandType


class CommandSubmitRequest(BaseModel):
    type: AgentCommandType
    payload: dict = Field(default_factory=dict)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=255)
    correlation_id: uuid.UUID | None = None
    ttl_seconds: int = Field(default=120, ge=5, le=3600)


class CommandOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    type: AgentCommandType
    status: str
    payload: dict
    result: dict | None
    error: str | None
    correlation_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime | None

    @classmethod
    def from_model(cls, command: AgentCommand) -> Self:
        return cls(
            id=command.id,
            agent_id=command.agent_id,
            type=command.command_type,
            status=command.status.value,
            payload=command.payload,
            result=command.result,
            error=command.error,
            correlation_id=command.correlation_id,
            created_at=command.created_at,
            expires_at=command.expires_at,
        )
