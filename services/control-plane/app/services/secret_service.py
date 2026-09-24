"""Secret key/value storage for applications.

Encrypted at rest (Phase 15, app/core/secret_crypto.py) since this module's
own earlier tracked gap: `SecretRecord.encrypted_value` now genuinely holds
a Fernet token, not plaintext. What Phase 6 already guaranteed and Phase 15
doesn't change: a value is set once, and every subsequent read through the
API (list, validation) only ever returns whether a key exists — never the
value itself. The two internal decrypt paths below (`get_secret_values`/
`get_secret_dict`) are for the Control Plane's own use only (log redaction,
injecting a value into a container's environment) and must never be
returned through an API response.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.db.models.secret import SecretRecord


def set_secret(session: Session, application_id: uuid.UUID, key: str, value: str) -> SecretRecord:
    encrypted = encrypt_secret(value)
    record = session.scalars(
        select(SecretRecord).where(
            SecretRecord.application_id == application_id, SecretRecord.key == key
        )
    ).first()
    if record is None:
        record = SecretRecord(application_id=application_id, key=key, encrypted_value=encrypted)
        session.add(record)
    else:
        record.encrypted_value = encrypted
    session.flush()
    return record


def get_secret_values(session: Session, application_id: uuid.UUID) -> list[str]:
    """Decrypted values for internal use only (log redaction) — never
    returned through an API response.
    """
    stmt = select(SecretRecord.encrypted_value).where(SecretRecord.application_id == application_id)
    return [decrypt_secret(v) for v in session.scalars(stmt).all() if v]


def get_secret_dict(session: Session, application_id: uuid.UUID) -> dict[str, str]:
    """key -> decrypted value, for injecting into a Linux Docker container's
    environment at start_instance time (app.services.deployment_service).
    Internal use only — never returned through an API response.
    """
    stmt = select(SecretRecord.key, SecretRecord.encrypted_value).where(
        SecretRecord.application_id == application_id
    )
    return {key: decrypt_secret(value) for key, value in session.execute(stmt).all() if value}


def list_secret_keys(session: Session, application_id: uuid.UUID) -> list[SecretRecord]:
    stmt = (
        select(SecretRecord)
        .where(SecretRecord.application_id == application_id)
        .order_by(SecretRecord.key)
    )
    return list(session.scalars(stmt).all())


def delete_secret(session: Session, application_id: uuid.UUID, key: str) -> bool:
    record = session.scalars(
        select(SecretRecord).where(
            SecretRecord.application_id == application_id, SecretRecord.key == key
        )
    ).first()
    if record is None:
        return False
    session.delete(record)
    session.flush()
    return True
