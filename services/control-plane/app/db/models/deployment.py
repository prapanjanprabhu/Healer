import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import DeploymentStatus, DeploymentStepStatus
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Deployment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deployments"
    __table_args__ = (Index("ix_deployments_application_id_status", "application_id", "status"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DeploymentStatus] = mapped_column(
        Enum(DeploymentStatus, name="deployment_status"),
        nullable=False,
        default=DeploymentStatus.PENDING,
    )
    instance_count: Mapped[int] = mapped_column(Integer, nullable=False)
    zero_downtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # "deploy" (Phase 7 bootstrap), "scale" (Phase 9), "blue_green" or
    # "rollback" (Phase 11) — lets the dashboard's deployment timeline and
    # `GET /deployments` distinguish what kind of operation this was.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="deploy")
    # A short, human-readable summary of why a blue-green switch or rollback
    # didn't happen — set once, alongside the terminal FAILED status; the
    # step/log rows still have the full detail. See app/services/release_service.py.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DeploymentStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deployment_steps"
    __table_args__ = (Index("ix_deployment_steps_deployment_id_status", "deployment_id", "status"),)

    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DeploymentStepStatus] = mapped_column(
        Enum(DeploymentStepStatus, name="deployment_step_status"),
        nullable=False,
        default=DeploymentStepStatus.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeploymentLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deployment_logs"
    __table_args__ = (
        Index("ix_deployment_logs_deployment_id_created_at", "deployment_id", "created_at"),
    )

    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployment_steps.id", ondelete="SET NULL"), nullable=True
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
