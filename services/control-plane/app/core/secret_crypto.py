"""Encryption at rest for application secrets (Phase 15) — replaces the
plaintext `SecretRecord.encrypted_value` this project carried as a known,
tracked gap since Phase 6 (see that model's own prior docstring history).

Uses Fernet (AES-128-CBC + HMAC-SHA256, from the `cryptography` package) —
authenticated symmetric encryption, appropriate here because only the
Control Plane itself ever needs the value back (injected into a container's
environment or otherwise used internally — never returned through an API
response, see app/services/secret_service.py). The key is derived from
`settings.secret_encryption_key`, an arbitrary passphrase like every other
"change-me-*" value in this codebase, via SHA-256 — one bootstrap step
(set an env var), not two (set an env var, then also pre-generate and store
a separately-formatted key).
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretDecryptionError(Exception):
    """The stored value could not be decrypted — wrong key, or corrupted
    data. Never raised for a value that was simply never set.
    """


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.secret_encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        # InvalidToken covers a wrong key or corrupted ciphertext; a
        # malformed token that isn't even valid base64 raises a plain
        # ValueError from Fernet's own decoding step before that check runs.
        raise SecretDecryptionError(
            "secret value could not be decrypted — wrong SECRET_ENCRYPTION_KEY or corrupted data"
        ) from exc
