from sqlalchemy import select

from app.db.models.user import Role
from app.db.seed import DEFAULT_ROLES, seed_roles


def test_roles_are_already_seeded_by_migrations(db_session):
    names = set(db_session.scalars(select(Role.name)).all())
    assert set(DEFAULT_ROLES) <= names


def test_seed_roles_is_idempotent(db_session):
    seed_roles(db_session)
    seed_roles(db_session)

    names = db_session.scalars(select(Role.name)).all()
    for role_name in DEFAULT_ROLES:
        assert names.count(role_name) == 1
