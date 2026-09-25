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


def _redact(value):
    """Masks the *values* of any "env" dict found anywhere in a command
    payload/result, keeping the keys visible. `_build_start_instance_payload`
    (app/services/deployment_service.py) injects decrypted application
    secrets into `payload["linux"]["env"]` so the Agent can set them as
    container environment variables — necessary for the Agent, but this is
    the API response boundary (CommandOut), the same one `SecretKeyOut`
    already enforces as write-only elsewhere, so the real values must never
    round-trip back out through GET/POST /agents/{id}/commands.
    """
    if isinstance(value, dict):
        return {
            k: ({inner_k: "[REDACTED]" for inner_k in v} if k == "env" and isinstance(v, dict) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


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
            payload=_redact(command.payload),
            result=_redact(command.result),
            error=command.error,
            correlation_id=command.correlation_id,
            created_at=command.created_at,
            expires_at=command.expires_at,
        )
