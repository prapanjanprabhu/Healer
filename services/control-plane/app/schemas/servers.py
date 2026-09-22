import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.enums import ServerOS, ServerStatus


class ServerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    hostname: str = Field(min_length=1, max_length=255)
    os: ServerOS


class ServerOut(BaseModel):
    id: uuid.UUID
    name: str
    hostname: str
    os: ServerOS
    status: ServerStatus
    online: bool
    agent_version: str | None = None
    last_seen_at: datetime | None = None
    created_at: datetime


class EnrollmentTokenIssuedOut(BaseModel):
    id: uuid.UUID
    token: str  # raw token — returned exactly once, never persisted in the clear
    expires_at: datetime


class EnrollmentTokenOut(BaseModel):
    id: uuid.UUID
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
