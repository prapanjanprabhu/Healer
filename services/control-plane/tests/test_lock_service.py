from datetime import UTC, datetime, timedelta

from app.services import lock_service
from app.services.lock_service import OperationLockHeldError
from tests.factories import make_application


def test_acquire_succeeds_on_an_unlocked_application(db_session):
    application = make_application(db_session)
    lock_service.acquire(db_session, application.id, "deploy")
    db_session.refresh(application)
    assert application.operation_lock == "deploy"
    assert application.operation_lock_acquired_at is not None


def test_acquire_raises_while_another_operation_holds_the_lock(db_session):
    application = make_application(db_session)
    lock_service.acquire(db_session, application.id, "deploy")

    try:
        lock_service.acquire(db_session, application.id, "scale")
        assert False, "expected OperationLockHeldError"
    except OperationLockHeldError as exc:
        assert "'deploy'" in str(exc)


def test_release_clears_the_lock(db_session):
    application = make_application(db_session)
    token = lock_service.acquire(db_session, application.id, "deploy")
    lock_service.release(db_session, application.id, token)
    db_session.refresh(application)
    assert application.operation_lock is None
    assert application.operation_lock_acquired_at is None

    # Released, so a different operation can now acquire it.
    lock_service.acquire(db_session, application.id, "scale")
    db_session.refresh(application)
    assert application.operation_lock == "scale"


def test_a_stale_lock_can_be_reacquired(db_session):
    application = make_application(db_session)
    lock_service.acquire(db_session, application.id, "deploy")
    # Simulate a crashed background task: the lock was never released and is
    # now older than the stale-lock cutoff.
    application.operation_lock_acquired_at = (
        datetime.now(UTC) - lock_service.STALE_LOCK_AFTER - timedelta(minutes=1)
    )
    db_session.commit()

    lock_service.acquire(db_session, application.id, "scale")
    db_session.refresh(application)
    assert application.operation_lock == "scale"


def test_release_with_a_stale_token_does_not_clear_a_newer_lock(db_session):
    """A slow-but-legitimate holder that ran past STALE_LOCK_AFTER must not
    be able to clear the lock a second operation validly reacquired in the
    meantime — that would let a *third* operation start concurrently with
    the second, defeating the whole point of the lock.
    """
    application = make_application(db_session)
    stale_token = lock_service.acquire(db_session, application.id, "deploy")
    application.operation_lock_acquired_at = (
        datetime.now(UTC) - lock_service.STALE_LOCK_AFTER - timedelta(minutes=1)
    )
    db_session.commit()

    # A second operation reacquires the now-stale lock.
    lock_service.acquire(db_session, application.id, "scale")
    db_session.refresh(application)
    assert application.operation_lock == "scale"

    # The first (slow) operation finally finishes and releases using its
    # original, now-stale token — this must be a no-op, not a steal.
    lock_service.release(db_session, application.id, stale_token)
    db_session.refresh(application)
    assert application.operation_lock == "scale"
    assert application.operation_lock_acquired_at is not None


def test_force_release_clears_the_lock_regardless_of_owner(db_session):
    application = make_application(db_session)
    lock_service.acquire(db_session, application.id, "deploy")
    lock_service.force_release(db_session, application.id)
    db_session.refresh(application)
    assert application.operation_lock is None
    assert application.operation_lock_acquired_at is None
