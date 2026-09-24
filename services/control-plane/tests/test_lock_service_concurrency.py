"""A genuine concurrency test for lock_service.acquire — every other lock
test in test_lock_service.py calls acquire twice sequentially in the same
db_session, which would not catch a check-then-set race if acquire's SQL
weren't a single atomic UPDATE. This spins up real threads, each on its own
genuine SessionLocal() connection (db_session's SAVEPOINT-based session
can't be shared safely across threads/connections — same reasoning as
test_health_monitor.py's real_session fixture), and confirms exactly one
of many simultaneous acquire attempts wins.
"""

import threading

from app.db.session import SessionLocal
from app.services import lock_service
from app.services.lock_service import OperationLockHeldError
from tests.factories import make_application

THREAD_COUNT = 10


def test_only_one_of_many_concurrent_acquires_succeeds():
    setup_session = SessionLocal()
    application = make_application(setup_session)
    application_id = application.id
    setup_session.commit()

    start_barrier = threading.Barrier(THREAD_COUNT)
    results: list[str] = []
    results_lock = threading.Lock()

    def attempt(operation_name: str) -> None:
        session = SessionLocal()
        try:
            start_barrier.wait(timeout=5)  # maximize real overlap
            try:
                lock_service.acquire(session, application_id, operation_name)
                outcome = "acquired"
            except OperationLockHeldError:
                outcome = "blocked"
            with results_lock:
                results.append(outcome)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt, args=(f"op-{i}",)) for i in range(THREAD_COUNT)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    try:
        assert len(results) == THREAD_COUNT, "not every thread finished in time"
        assert results.count("acquired") == 1, f"expected exactly one winner, got {results}"
        assert results.count("blocked") == THREAD_COUNT - 1
    finally:
        cleanup_session = SessionLocal()
        app_row = cleanup_session.get(type(application), application_id)
        if app_row is not None:
            cleanup_session.delete(app_row)
        cleanup_session.commit()
        cleanup_session.close()
