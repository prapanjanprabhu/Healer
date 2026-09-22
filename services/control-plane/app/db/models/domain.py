import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Domain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "domains"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    cert_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class UpstreamGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "upstream_groups"
    __table_args__ = (
        UniqueConstraint("domain_id", "name", name="uq_upstream_groups_domain_id_name"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class UpstreamInstance(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "upstream_instances"
    __table_args__ = (
        UniqueConstraint(
            "upstream_group_id", "instance_id", name="uq_upstream_instances_group_instance"
        ),
    )

    upstream_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("upstream_groups.id", ondelete="CASCADE"), nullable=False
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id", ondelete="CASCADE"), nullable=False
    )
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
