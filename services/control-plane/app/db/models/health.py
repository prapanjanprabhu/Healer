import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import HealthCheckType
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class HealthCheck(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "health_checks"
    __table_args__ = (UniqueConstraint("application_id", name="uq_health_checks_application_id"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    check_type: Mapped[HealthCheckType] = mapped_column(
        Enum(HealthCheckType, name="health_check_type"),
        nullable=False,
        default=HealthCheckType.HTTP,
    )
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    healthy_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    unhealthy_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # None (the default) preserves the Phase 9 behavior — any non-5xx counts
    # as healthy. Set to require an exact status code instead.
    expected_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Bounds for Phase 10's self-healing — see app/services/self_healing_service.py.
    max_restart_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    restart_cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)


class HealthCheckResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "health_check_results"
    __table_args__ = (
        Index("ix_health_check_results_instance_id_checked_at", "instance_id", "checked_at"),
        Index(
            "ix_health_check_results_health_check_id_checked_at", "health_check_id", "checked_at"
        ),
    )

    health_check_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("health_checks.id", ondelete="CASCADE"), nullable=False
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id", ondelete="CASCADE"), nullable=False
    )
    healthy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
