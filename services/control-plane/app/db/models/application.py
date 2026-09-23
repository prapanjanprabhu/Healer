import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import AdapterType, InstanceStatus, ReleaseStatus, SourceType
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    adapter_type: Mapped[AdapterType] = mapped_column(
        Enum(AdapterType, name="adapter_type"), nullable=False
    )
    # The server this application is (to be) deployed on. V1 is single-server
    # per application — multi-server scaling is Phase 9.
    server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="SET NULL"), nullable=True
    )
    # The full parsed healer.yaml descriptor (adapter-specific fields like
    # python_executable/wsgi_module or internal_port live here rather than as
    # a dozen nullable columns that only apply to one adapter). See
    # app/schemas/healer_yaml.py — this is that schema's .model_dump().
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    port_range_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_range_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), nullable=False
    )
    location: Mapped[str] = mapped_column(Text, nullable=False)
    # Git ref (branch/tag/sha) when source_type is GIT; unused otherwise.
    ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Configuration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "configurations"
    __table_args__ = (
        UniqueConstraint("application_id", "key", name="uq_configurations_application_key"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class Release(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "releases"
    __table_args__ = (
        Index("ix_releases_application_id_created_at", "application_id", "created_at"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    ref: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ReleaseStatus] = mapped_column(
        Enum(ReleaseStatus, name="release_status"), nullable=False, default=ReleaseStatus.PENDING
    )
    # Populated from the Agent's deploy_release result once it succeeds —
    # absolute paths on the target server, not meaningful until then.
    release_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    venv_python: Mapped[str | None] = mapped_column(Text, nullable=True)


class Instance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "instances"
    __table_args__ = (
        UniqueConstraint("server_id", "port", name="uq_instances_server_id_port"),
        Index("ix_instances_application_id_status", "application_id", "status"),
        Index("ix_instances_server_id_status", "server_id", "status"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[InstanceStatus] = mapped_column(
        Enum(InstanceStatus, name="instance_status"), nullable=False, default=InstanceStatus.PENDING
    )
    # Deterministic, e.g. "Healer-rit-academic-erp-9034" — see
    # app/services/deployment_service.py. Assigned at Instance creation time
    # since it's derived from the (stable) application slug and the
    # allocated port, not from anything the Agent reports back.
    service_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
