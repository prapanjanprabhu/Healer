import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: uuid.UUID
    notification_type: str
    message: str
    read_at: datetime | None
    created_at: datetime
