import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import UUIDPrimaryKeyMixin


class MetricsSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "metrics_snapshots"
    __table_args__ = (
        Index("ix_metrics_snapshots_server_id_recorded_at", "server_id", "recorded_at"),
    )

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    cpu_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    memory_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    disk_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
