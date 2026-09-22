import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import AgentCommandStatus, AgentCommandType, AgentStatus
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"),
        nullable=False,
        default=AgentStatus.DISCONNECTED,
        index=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_connections"
    __table_args__ = (
        Index("ix_agent_connections_agent_id_connected_at", "agent_id", "connected_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote_addr: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AgentCommand(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_commands"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_agent_commands_idempotency_key"),
        Index("ix_agent_commands_agent_id_status", "agent_id", "status"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    command_type: Mapped[AgentCommandType] = mapped_column(
        Enum(AgentCommandType, name="agent_command_type"), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[AgentCommandStatus] = mapped_column(
        Enum(AgentCommandStatus, name="agent_command_status"),
        nullable=False,
        default=AgentCommandStatus.PENDING,
    )


class AgentEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_events"
    __table_args__ = (Index("ix_agent_events_agent_id_occurred_at", "agent_id", "occurred_at"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
