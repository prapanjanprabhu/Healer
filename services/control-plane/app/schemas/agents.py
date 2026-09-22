import uuid

from pydantic import BaseModel, Field


class AgentEnrollRequest(BaseModel):
    token: str = Field(min_length=1)


class AgentEnrollResponse(BaseModel):
    agent_id: uuid.UUID
    server_id: uuid.UUID
    credential: str  # raw — returned exactly once
    control_plane_ws_url: str
