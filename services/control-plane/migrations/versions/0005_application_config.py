"""application config for healer.yaml

Adds the target server, the full parsed healer.yaml descriptor (JSONB), and
a port allocation range to applications; a git ref to sources; and two new
source types (dockerfile, image) for the linux/docker adapter.

`sources`/`applications` are empty in every environment this runs against
(Phase 6 is the first phase with an application-creation API), so the new
enum values are added with plain `ALTER TYPE ... ADD VALUE` — Postgres has
no `DROP VALUE`, so downgrade leaves them in place (harmless: nothing reads
or requires their absence) rather than doing the full rename/recreate dance
used in 0004 for enum sets that were actually changing member-for-member.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-23 03:31:39.323221

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

FK_NAME = "fk_applications_server_id_servers"


def upgrade() -> None:
    op.execute("ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'DOCKERFILE'")
    op.execute("ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'IMAGE'")

    op.add_column("applications", sa.Column("server_id", sa.UUID(), nullable=True))
    op.add_column(
        "applications", sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("applications", sa.Column("port_range_start", sa.Integer(), nullable=True))
    op.add_column("applications", sa.Column("port_range_end", sa.Integer(), nullable=True))
    op.create_foreign_key(
        FK_NAME, "applications", "servers", ["server_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("sources", sa.Column("ref", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "ref")
    op.drop_constraint(FK_NAME, "applications", type_="foreignkey")
    op.drop_column("applications", "port_range_end")
    op.drop_column("applications", "port_range_start")
    op.drop_column("applications", "config")
    op.drop_column("applications", "server_id")
    # source_type's DOCKERFILE/IMAGE values are intentionally left in place —
    # see the module docstring.
