"""Secret key/value storage for applications.

Encryption-at-rest is not implemented yet (`SecretRecord.encrypted_value`
is a placeholder column — see docs/data-model.md); this is a known, tracked
gap for a later phase, not something quietly pretended away. What Phase 6
guarantees is the API contract: a value is set once, and every subsequent
read (list, validation) only ever returns whether a key exists — never the
value itself.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.secret import SecretRecord


def set_secret(session: Session, application_id: uuid.UUID, key: str, value: str) -> SecretRecord:
    record = session.scalars(
        select(SecretRecord).where(
            SecretRecord.application_id == application_id, SecretRecord.key == key
        )
    ).first()
    if record is None:
        record = SecretRecord(application_id=application_id, key=key, encrypted_value=value)
        session.add(record)
    else:
        record.encrypted_value = value
    session.flush()
    return record


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
