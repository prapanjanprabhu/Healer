"""replica scaling: min/max/desired replicas, an operation lock on
applications, a DRAINING instance status, response_time_ms on health check
results, and instances.deployment_id (which Deployment last touched an
instance — a scale operation shares its release with prior deploys, so
release_id alone can't identify which instances one specific
deploy/scale Deployment created or stopped).

See app/services/scale_service.py and app/services/lock_service.py.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("min_replicas", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "applications",
        sa.Column("max_replicas", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "applications",
        sa.Column("desired_replicas", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("applications", sa.Column("operation_lock", sa.String(length=50), nullable=True))
    op.add_column(
        "applications",
        sa.Column("operation_lock_acquired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "health_check_results", sa.Column("response_time_ms", sa.Integer(), nullable=True)
    )
    op.add_column("instances", sa.Column("deployment_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_instances_deployment_id",
        "instances",
        "deployments",
        ["deployment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_instances_deployment_id"), "instances", ["deployment_id"], unique=False
    )

    # Postgres native enums require ADD VALUE outside the migration's normal
    # transaction (a new enum value can't be used in the same transaction
    # that adds it) — autocommit_block() is Alembic's supported way to do
    # that mid-migration rather than needing a separate revision.
    #
    # The label must be 'DRAINING' (matching InstanceStatus.DRAINING.*name*,
    # not .value) — SQLAlchemy's Enum type persists PEP-435 enums by their
    # member *name* by default (no values_callable is configured anywhere
    # in this codebase), which is why every existing label here is
    # upper-case even though every Python enum *value* is lower-case.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE instance_status ADD VALUE IF NOT EXISTS 'DRAINING'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — removing 'draining' would
    # require rebuilding the enum type from scratch. Left in place on
    # downgrade (harmless: an unused enum value); everything else below is
    # fully reversible.
    op.drop_index(op.f("ix_instances_deployment_id"), table_name="instances")
    op.drop_constraint("fk_instances_deployment_id", "instances", type_="foreignkey")
    op.drop_column("instances", "deployment_id")
    op.drop_column("health_check_results", "response_time_ms")
    op.drop_column("applications", "operation_lock_acquired_at")
    op.drop_column("applications", "operation_lock")
    op.drop_column("applications", "desired_replicas")
    op.drop_column("applications", "max_replicas")
    op.drop_column("applications", "min_replicas")
