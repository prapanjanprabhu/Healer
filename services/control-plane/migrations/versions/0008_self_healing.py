"""active health checks and bounded self-healing: an expected-status and
restart-attempt/cooldown config on health_checks, healing bookkeeping on
instances, and a RESTARTING instance status.

See app/services/self_healing_service.py and app/services/health_monitor.py.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-23 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("health_checks", sa.Column("expected_status", sa.Integer(), nullable=True))
    op.add_column(
        "health_checks",
        sa.Column("max_restart_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "health_checks",
        sa.Column("restart_cooldown_seconds", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "instances",
        sa.Column("healing_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "instances",
        sa.Column("last_healing_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("instances", sa.Column("failure_reason", sa.Text(), nullable=True))

    # See migration 0007's note on why this must be upper-case and outside
    # the normal transaction.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE instance_status ADD VALUE IF NOT EXISTS 'RESTARTING'")


def downgrade() -> None:
    op.drop_column("instances", "failure_reason")
    op.drop_column("instances", "last_healing_attempt_at")
    op.drop_column("instances", "healing_attempts")
    op.drop_column("health_checks", "restart_cooldown_seconds")
    op.drop_column("health_checks", "max_restart_attempts")
    op.drop_column("health_checks", "expected_status")
