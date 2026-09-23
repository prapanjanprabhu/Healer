import uuid
from datetime import datetime

from pydantic import BaseModel


class DeployTriggerResponse(BaseModel):
    deployment_id: uuid.UUID
    release_id: uuid.UUID
    instance_id: uuid.UUID
    port: int
    service_name: str


class DeploymentStepOut(BaseModel):
    name: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None


class DeploymentLogOut(BaseModel):
    step_id: uuid.UUID | None
    level: str
    message: str
    created_at: datetime


class DeploymentInstanceOut(BaseModel):
    id: uuid.UUID
    server_id: uuid.UUID
    port: int
    service_name: str | None
    status: str


class DeploymentDetailOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    release_id: uuid.UUID
    release_version: str
    status: str
    instance: DeploymentInstanceOut | None
    steps: list[DeploymentStepOut]
    logs: list[DeploymentLogOut]
    created_at: datetime
    updated_at: datetime
