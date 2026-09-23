import uuid
from datetime import datetime

from pydantic import BaseModel


class ReleaseTriggerResponse(BaseModel):
    deployment_id: uuid.UUID
    warnings: list[str]


class RollbackRequest(BaseModel):
    release_id: uuid.UUID


class ReleaseOut(BaseModel):
    id: uuid.UUID
    ref: str
    status: str
    is_active: bool
    created_at: datetime
