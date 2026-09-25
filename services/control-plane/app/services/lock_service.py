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


def acquire(session: Session, application_id: uuid.UUID, operation: str) -> datetime:
    """Returns the `operation_lock_acquired_at` timestamp this call wrote —
    a fencing token the caller must pass back to `release()` so a lock that
    was reacquired out from under a stale holder (see STALE_LOCK_AFTER)
    can't then be cleared by that original, still-running holder's eventual
    `finally: release(...)`. See `release()`.
    """
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
    return now


def release(session: Session, application_id: uuid.UUID, acquired_at: datetime) -> None:
    """Only clears the lock if it's still the exact one `acquire()` handed
    back (`operation_lock_acquired_at == acquired_at`). Without this check,
    a slow-but-legitimate operation that ran past STALE_LOCK_AFTER — during
    which a different operation validly reacquired the lock as "abandoned"
    — would clear that newer operation's lock out from under it in its own
    `finally` block once it finally finishes, letting a third operation
    start concurrently with the second. This is what actually enforces "one
    operation at a time", not just `acquire()`'s staleness check alone.
    """
    session.execute(
        update(Application)
        .where(
            Application.id == application_id,
            Application.operation_lock_acquired_at == acquired_at,
        )
        .values(operation_lock=None, operation_lock_acquired_at=None)
    )
    session.commit()


def force_release(session: Session, application_id: uuid.UUID) -> None:
    """Unconditionally clears the lock regardless of who (if anyone) holds
    it. For control-plane restart recovery only (reconcile_service): the
    operation that acquired the lock is known to be gone — its process
    doesn't exist anymore to ever call `release()` itself — rather than
    merely slow, so there's no legitimate current holder whose lock this
    could steal.
    """
    session.execute(
        update(Application)
        .where(Application.id == application_id)
        .values(operation_lock=None, operation_lock_acquired_at=None)
    )
    session.commit()
