import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import ServerOS, ServerStatus
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Server(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "servers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    os: Mapped[ServerOS] = mapped_column(Enum(ServerOS, name="server_os"), nullable=False)
    status: Mapped[ServerStatus] = mapped_column(
        Enum(ServerStatus, name="server_status"),
        nullable=False,
        default=ServerStatus.PENDING,
        index=True,
    )


class EnrollmentToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "enrollment_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_enrollment_tokens_token_hash"),)

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when an enroll call successfully consumes the token.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when an administrator invalidates the token before it's used —
    # distinct from used_at so "consumed" and "revoked" are never confused.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
