from sqlalchemy.orm import Session

from app.repositories.role_repository import RoleRepository

DEFAULT_ROLES = ["Administrator", "Operator", "Viewer"]


def seed_roles(session: Session) -> None:
    """Idempotently ensure the default roles exist.

    Flushes but does not commit — committing is the caller's responsibility,
    consistent with the rest of the repository layer (see app/repositories).
    Also applied as a data migration (see
    migrations/versions/0003_seed_default_roles.py) so a clean database has
    these roles immediately after `alembic upgrade head` with no separate
    step required; this function exists for tests and any future in-process
    reseeding.
    """
    repo = RoleRepository(session)
    for name in DEFAULT_ROLES:
        repo.get_or_create(name)
