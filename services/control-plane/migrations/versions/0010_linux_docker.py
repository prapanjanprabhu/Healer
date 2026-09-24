"""Linux Docker adapter (Phase 13): the built/pulled image reference a
release runs from, mirroring release_dir/venv_python for the Windows
adapter.

See app/services/deployment_service.py, app/services/release_service.py.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-24 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("releases", sa.Column("image_ref", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("releases", "image_ref")
