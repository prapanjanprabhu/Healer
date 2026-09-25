"""Instance rows are never deleted (kept for the dashboard's instance
history — see list_instances in app/services/scale_service.py), so the
unconditional (server_id, port) uniqueness constraint let every terminal
(stopped/failed) instance permanently squat on its port forever. Every
blue-green deploy, scale-up and self-healing replacement allocates a fresh
port and never gets the old one back, so a typical small port range
exhausts after roughly a dozen such operations even though the OS port is
actually free. This replaces the plain constraint with a partial unique
index scoped to non-terminal statuses, so a dead instance's port becomes
reusable — see app/db/models/application.py's Instance.__table_args__ and
app/services/deployment_service.py's _allocate_instance.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-25 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_instances_server_id_port", "instances", type_="unique")
    op.create_index(
        "uq_instances_server_id_port_live",
        "instances",
        ["server_id", "port"],
        unique=True,
        # The Postgres enum's stored labels are the Python enum members'
        # *names* (SQLAlchemy's Enum default), i.e. uppercase 'STOPPED'/
        # 'FAILED' — not InstanceStatus.STOPPED.value ("stopped").
        postgresql_where=sa.text("status NOT IN ('STOPPED'::instance_status, 'FAILED'::instance_status)"),
    )


def downgrade() -> None:
    op.drop_index("uq_instances_server_id_port_live", table_name="instances")
    op.create_unique_constraint(
        "uq_instances_server_id_port", "instances", ["server_id", "port"]
    )
