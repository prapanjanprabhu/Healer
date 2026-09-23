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
    lock_service.acquire(db_session, application.id, "deploy")
    lock_service.release(db_session, application.id)
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
