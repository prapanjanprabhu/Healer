"""Administrator-only user/role management (Phase 14) — the dashboard's
Users page. Roles are the fixed V1 set (Administrator/Operator/Viewer, see
app/domain/permissions.py); there is no custom-role creation in V1, only
assigning a user one or more of these three.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models.user import Role, User, UserRole
from app.domain.permissions import ROLE_PERMISSIONS
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository


class UserServiceError(Exception):
    """A request that can't be honored — surfaced as a 4xx by the route."""


VALID_ROLE_NAMES = set(ROLE_PERMISSIONS.keys())


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.email)).all())


def list_role_names() -> list[str]:
    return sorted(VALID_ROLE_NAMES)


def _validate_role_names(role_names: list[str]) -> None:
    if not role_names:
        raise UserServiceError("a user must have at least one role")
    unknown = set(role_names) - VALID_ROLE_NAMES
    if unknown:
        raise UserServiceError(f"unknown role(s): {', '.join(sorted(unknown))}")


def create_user(session: Session, *, email: str, password: str, role_names: list[str]) -> User:
    email = email.strip().lower()
    _validate_role_names(role_names)
    if UserRepository(session).get_by_email(email) is not None:
        raise UserServiceError("a user with this email already exists")

    user = User(email=email, password_hash=hash_password(password), is_active=True)
    session.add(user)
    session.flush()
    _set_roles(session, user, role_names)
    session.commit()
    return user


def set_user_roles(session: Session, user: User, role_names: list[str]) -> User:
    _validate_role_names(role_names)
    _set_roles(session, user, role_names)
    session.commit()
    return user


def _set_roles(session: Session, user: User, role_names: list[str]) -> None:
    session.query(UserRole).filter(UserRole.user_id == user.id).delete(synchronize_session=False)
    session.flush()
    role_repo = RoleRepository(session)
    for name in role_names:
        role: Role = role_repo.get_or_create(name)
        session.add(UserRole(user_id=user.id, role_id=role.id))
    session.flush()


def set_user_active(session: Session, user: User, active: bool) -> User:
    user.is_active = active
    session.commit()
    return user


def get_user(session: Session, user_id: uuid.UUID) -> User | None:
    return UserRepository(session).get(user_id)
