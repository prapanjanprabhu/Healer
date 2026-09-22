import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.cookies import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.core.security import decode_access_token
from app.db.models.user import User
from app.db.session import get_db
from app.domain.permissions import has_permission


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    roles: frozenset[str]


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="invalid or expired session"
        ) from exc

    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or expired session")

    return CurrentUser(id=user.id, email=user.email, roles=frozenset(payload.get("roles", [])))


def require_permission(permission: str):
    """Route dependency: 403s unless the current user's roles grant `permission`."""

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not has_permission(set(current_user.roles), permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
        return current_user

    return dependency


def verify_csrf(request: Request) -> None:
    """Double-submit CSRF check for cookie-authenticated mutating requests.

    The CSRF cookie is not HttpOnly, so only same-origin JS (which the
    dashboard is) can read it and echo it back as a header; a cross-site
    form or script can trigger the cookie-bearing request but can't read the
    cookie to produce a matching header. See app/core/cookies.py.
    """
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_value or not header_value or cookie_value != header_value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
