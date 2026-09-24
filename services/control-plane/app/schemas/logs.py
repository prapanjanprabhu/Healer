import uuid

from pydantic import BaseModel


class LogSourceOut(BaseModel):
    id: str
    type: str
    label: str
    instance_id: uuid.UUID | None


class LogChunkOut(BaseModel):
    lines: list[str]
    size: int
    end_offset: int
    truncated: bool
    not_found: bool
