"""A simple, race-safe per-application operation lock — see
`Application.operation_lock`/`operation_lock_acquired_at`.

Deploy, scale, and (eventually) restart all serialize on this same lock so
two conflicting operations can never run against one application at once.
Acquisition is a single conditional `UPDATE ... WHERE operation_lock IS NULL
OR operation_lock_acquired_at < <stale cutoff>`, which Postgres's row-level
locking makes atomic across concurrent requests — the loser simply updates
zero rows, no separate advisory lock or `SELECT ... FOR UPDATE` needed.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models.application import Application

# A lock older than this is treated as abandoned (e.g. the process holding
# it crashed or was killed mid-operation) and can be reacquired by anyone —
# long enough that a real multi-instance scale-up never trips it itself.
STALE_LOCK_AFTER = timedelta(minutes=20)


class OperationLockHeldError(Exception):
    """Another deploy/scale/restart is already in progress for this application."""


def acquire(session: Session, application_id: uuid.UUID, operation: str) -> None:
    now = datetime.now(UTC)
    stale_cutoff = now - STALE_LOCK_AFTER
    result = session.execute(
        update(Application)
        .where(
            Application.id == application_id,
            (Application.operation_lock.is_(None))
            | (Application.operation_lock_acquired_at < stale_cutoff),
        )
        .values(operation_lock=operation, operation_lock_acquired_at=now)
    )
    session.commit()
    if result.rowcount == 0:
        current = session.get(Application, application_id)
        held_as = current.operation_lock if current is not None else "unknown"
        raise OperationLockHeldError(
            f"a {held_as!r} operation is already in progress for this application"
        )


def release(session: Session, application_id: uuid.UUID) -> None:
    session.execute(
        update(Application)
        .where(Application.id == application_id)
        .values(operation_lock=None, operation_lock_acquired_at=None)
    )
    session.commit()
