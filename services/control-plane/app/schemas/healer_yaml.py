"""The versioned healer.yaml schema (v1).

`adapter` uses the same vocabulary as `AdapterType`
(`windows-waitress-service` / `linux-docker`) and the Agent's own reported
capabilities (`agent/cmd/healer-agent/main.go:adaptersForOS`) — one naming
scheme throughout the system rather than a separate one just for this file.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

HEALER_YAML_VERSION = 1

AdapterName = Literal["windows-waitress-service", "linux-docker"]
SourceTypeName = Literal["folder", "git", "dockerfile", "image"]


class SourceConfig(BaseModel):
    type: SourceTypeName
    location: str = Field(min_length=1, max_length=2000)
    ref: str | None = Field(default=None, max_length=255)


class WindowsAdapterConfig(BaseModel):
    python_executable: str = Field(min_length=1)
    requirements_file: str = "requirements.txt"
    manage_py: str = "manage.py"
    wsgi_module: str = Field(min_length=1)
    settings_module: str = Field(min_length=1)
    # Relative to the source root. Symlinked into per-application shared
    # storage on deploy (see docs/app-deployment.md) so they survive across
    # releases instead of being recreated empty each time.
    static_dir: str = "static"
    media_dir: str = "media"
    log_dir: str = "logs"
    # Extra directory/file basenames to exclude from the release snapshot,
    # beyond the Agent's built-in defaults (.git, venv, __pycache__, etc.).
    exclude: list[str] = Field(default_factory=list)


class LinuxAdapterConfig(BaseModel):
    internal_port: int = Field(ge=1, le=65535)


class HealthConfig(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    interval_seconds: int = Field(default=10, ge=1, le=3600)
    timeout_seconds: int = Field(default=5, ge=1, le=300)
    healthy_threshold: int = Field(default=2, ge=1, le=100)
    unhealthy_threshold: int = Field(default=3, ge=1, le=100)

    @model_validator(mode="after")
    def _path_is_absolute(self) -> "HealthConfig":
        if not self.path.startswith("/"):
            raise ValueError("health.path must start with '/'")
        return self


class PortRangeConfig(BaseModel):
    start: int = Field(ge=1, le=65535)
    end: int = Field(ge=1, le=65535)

    @model_validator(mode="after")
    def _range_is_sane(self) -> "PortRangeConfig":
        if self.end < self.start:
            raise ValueError("ports.end must be >= ports.start")
        return self


class DomainConfig(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    cert_path: str | None = None
    key_path: str | None = None


class HealerYamlV1(BaseModel):
    version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=255)
    adapter: AdapterName
    server_id: uuid.UUID | None = None
    source: SourceConfig
    windows: WindowsAdapterConfig | None = None
    linux: LinuxAdapterConfig | None = None
    health: HealthConfig
    ports: PortRangeConfig
    domain: DomainConfig | None = None
    # Secret KEY NAMES this application needs at runtime — never values.
    # Validated for existence only; see app/domain/app_validation.py.
    secrets: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _adapter_matches_source_and_section(self) -> "HealerYamlV1":
        if self.adapter == "windows-waitress-service":
            if self.windows is None:
                raise ValueError("adapter windows-waitress-service requires a `windows:` section")
            if self.source.type not in ("folder", "git"):
                raise ValueError(
                    "adapter windows-waitress-service requires source.type 'folder' or 'git'"
                )
        elif self.adapter == "linux-docker":
            if self.linux is None:
                raise ValueError("adapter linux-docker requires a `linux:` section")
            if self.source.type not in ("dockerfile", "image"):
                raise ValueError(
                    "adapter linux-docker requires source.type 'dockerfile' or 'image'"
                )
            if self.source.type == "image" and self.source.ref:
                raise ValueError("source.ref is not meaningful when source.type is 'image'")
        return self
