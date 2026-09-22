"""baseline (empty) — Phase 1 monorepo scaffold

Establishes migrations as a working, versioned mechanism against a real
PostgreSQL database before any schema (servers, applications, releases,
instances, deployments, audit log) is introduced in a later phase.

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
