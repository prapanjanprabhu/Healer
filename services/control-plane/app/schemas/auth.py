import uuid

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    roles: list[str]


class MessageResponse(BaseModel):
    message: str
