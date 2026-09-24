import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogEntryOut(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_email: str | None
    action: str
    target_type: str
    target_id: str
    detail: dict | None
    occurred_at: datetime
