import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.healer_yaml import HealerYamlV1


class ApplicationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    adapter_type: str
    server_id: uuid.UUID | None
    config: dict
    port_range_start: int | None
    port_range_end: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, application) -> "ApplicationOut":
        return cls(
            id=application.id,
            name=application.name,
            slug=application.slug,
            adapter_type=application.adapter_type.value,
            server_id=application.server_id,
            config=application.config or {},
            port_range_start=application.port_range_start,
            port_range_end=application.port_range_end,
            created_at=application.created_at,
            updated_at=application.updated_at,
        )


class ParseYamlRequest(BaseModel):
    yaml_text: str


class ParseErrorOut(BaseModel):
    field: str
    message: str


class ParseYamlResponse(BaseModel):
    ok: bool
    config: HealerYamlV1 | None = None
    errors: list[ParseErrorOut] = []


class ValidationIssueOut(BaseModel):
    field: str
    severity: str
    message: str


class ValidationResponse(BaseModel):
    ok: bool
    issues: list[ValidationIssueOut]


class SecretSetRequest(BaseModel):
    key: str
    value: str


class SecretKeyOut(BaseModel):
    key: str
    created_at: datetime
    updated_at: datetime
