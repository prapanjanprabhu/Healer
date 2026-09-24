import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_token, hash_password, hash_token, verify_password
from app.db.models.user import RefreshSession, User
from app.repositories.user_repository import UserRepository


class AuthError(Exception):
    """Raised for any authentication failure. The message is a stable code
    (e.g. "invalid_credentials"), never user input or a secret — callers
    decide what, if anything, to expose in the HTTP response.
    """


def authenticate(session: Session, email: str, password: str) -> User:
    user = UserRepository(session).get_by_email(email.strip().lower())
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError("invalid_credentials")
    return user


def get_role_names(user: User) -> list[str]:
    return sorted({user_role.role.name for user_role in user.roles})


def change_password(
    session: Session, user: User, *, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AuthError("invalid_credentials")
    user.password_hash = hash_password(new_password)
    _revoke_all_for_user(session, user.id)  # force re-login on every other session
    session.commit()


def create_refresh_session(session: Session, user: User) -> tuple[str, RefreshSession]:
    raw_token = generate_token()
    row = RefreshSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    session.add(row)
    session.flush()
    return raw_token, row


def rotate_refresh_session(session: Session, raw_token: str) -> tuple[str, RefreshSession, User]:
    """Validate + revoke the presented refresh token and issue a new one.

    If the presented token was already revoked, that's a replay of a token
    that should no longer exist — treated as possible theft, so every active
    session for that user is revoked (forces re-login everywhere).
    """
    row = (
        session.query(RefreshSession)
        .filter(RefreshSession.token_hash == hash_token(raw_token))
        .first()
    )
    if row is None:
        raise AuthError("invalid_refresh_token")

    now = datetime.now(UTC)
    if row.revoked_at is not None:
        _revoke_all_for_user(session, row.user_id)
        raise AuthError("refresh_token_reused")
    if row.expires_at < now:
        raise AuthError("refresh_token_expired")

    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthError("invalid_user")

    row.revoked_at = now
    new_raw_token, new_row = create_refresh_session(session, user)
    session.flush()
    return new_raw_token, new_row, user


def revoke_refresh_session(session: Session, raw_token: str) -> uuid.UUID | None:
    """Revoke the session for this refresh token; returns its user_id (for
    audit logging) or None if the token doesn't match any session.
    """
    row = (
        session.query(RefreshSession)
        .filter(RefreshSession.token_hash == hash_token(raw_token))
        .first()
    )
    if row is None:
        return None
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        session.flush()
    return row.user_id


def _revoke_all_for_user(session: Session, user_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    rows = (
        session.query(RefreshSession)
        .filter(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
        .all()
    )
    for row in rows:
        row.revoked_at = now
    session.flush()
