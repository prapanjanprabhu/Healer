import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"

# bcrypt silently ignores/rejects bytes past 72 — truncate explicitly so
# behavior is defined rather than backend-dependent.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(raw, password_hash.encode("utf-8"))


def hash_token(raw_token: str) -> str:
    """One-way hash for refresh tokens stored at rest — never store the raw token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(user_id: str, roles: list[str]) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "roles": roles,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.control_plane_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.control_plane_secret_key, algorithms=["HS256"])
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload
