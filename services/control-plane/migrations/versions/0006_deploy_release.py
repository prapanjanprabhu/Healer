"""release/instance bookkeeping for the deploy pipeline

Adds `release_dir`/`venv_python` to `releases` (populated from the Agent's
deploy_release result once it succeeds) and `service_name` to `instances`
(deterministic from the application slug + allocated port, assigned at
Instance creation time). See app/services/deployment_service.py.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-23 05:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("releases", sa.Column("release_dir", sa.Text(), nullable=True))
    op.add_column("releases", sa.Column("venv_python", sa.Text(), nullable=True))
    op.add_column("instances", sa.Column("service_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("instances", "service_name")
    op.drop_column("releases", "venv_python")
    op.drop_column("releases", "release_dir")
