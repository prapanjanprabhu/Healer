import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UserSummaryOut(BaseModel):
    id: uuid.UUID
    email: str
    roles: list[str]
    is_active: bool
    created_at: datetime


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    roles: list[str] = Field(min_length=1)


class SetUserRolesRequest(BaseModel):
    roles: list[str] = Field(min_length=1)
