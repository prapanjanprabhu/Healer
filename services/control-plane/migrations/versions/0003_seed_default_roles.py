"""seed default roles

Inserts the three V1 roles (Administrator, Operator, Viewer) so a clean
database has them immediately after `alembic upgrade head` — no separate
seed step required. Idempotent (ON CONFLICT DO NOTHING on the unique role
name), safe to re-run. Downgrade removes exactly these three rows by name,
leaving any roles added later untouched.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-22 09:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

DEFAULT_ROLES = ["Administrator", "Operator", "Viewer"]

roles_table = sa.table(
    "roles",
    sa.column("id", sa.UUID()),
    sa.column("name", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    connection = op.get_bind()
    for name in DEFAULT_ROLES:
        connection.execute(
            sa.text(
                "INSERT INTO roles (id, name, created_at, updated_at) "
                "VALUES (:id, :name, now(), now()) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), "name": name},
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM roles WHERE name = ANY(:names)"),
        {"names": DEFAULT_ROLES},
    )
