"""blue-green deployment and rollback: which release Nginx currently routes
to, release retention, and a deployment kind/failure_reason for the
dashboard's timeline.

See app/services/release_service.py.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-24 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("active_release_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_applications_active_release_id",
        "applications",
        "releases",
        ["active_release_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "applications",
        sa.Column("release_retention_count", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "deployments",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="deploy"),
    )
    op.add_column("deployments", sa.Column("failure_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployments", "failure_reason")
    op.drop_column("deployments", "kind")
    op.drop_column("applications", "release_retention_count")
    op.drop_constraint("fk_applications_active_release_id", "applications", type_="foreignkey")
    op.drop_column("applications", "active_release_id")
