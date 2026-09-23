import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ScaleTriggerRequest(BaseModel):
    desired_replicas: int = Field(ge=1)


class ScaleTriggerResponse(BaseModel):
    deployment_id: uuid.UUID
    desired_replicas: int


class InstanceOut(BaseModel):
    id: uuid.UUID
    port: int
    server_id: uuid.UUID
    server_name: str
    status: str
    release_version: str
    service_name: str | None
    healthy: bool | None
    response_time_ms: int | None
    last_checked_at: datetime | None
    failure_reason: str | None
    healing_attempts: int
    created_at: datetime
