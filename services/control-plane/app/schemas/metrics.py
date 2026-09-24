import uuid
from datetime import datetime

from pydantic import BaseModel


class MetricsSnapshotOut(BaseModel):
    server_id: uuid.UUID
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    recorded_at: datetime
