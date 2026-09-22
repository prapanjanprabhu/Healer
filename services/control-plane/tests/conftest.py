import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import engine, get_db
from app.main import app


@pytest.fixture()
def db_session():
    """A Session bound to a single connection/transaction that is rolled
    back after the test, so tests never leave data behind in the shared
    dev/test Postgres instance and can run in any order.

    `join_transaction_mode="create_savepoint"` lets application code call
    `session.commit()` (as the real `get_db` dependency does per request —
    see the `client` fixture) without ending the outer transaction: commit
    only releases/reopens a SAVEPOINT, so the final rollback below still
    undoes everything.

    Requires the schema to already be migrated to head (`alembic upgrade
    head`) — this fixture does not create tables itself.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    session: Session = session_factory()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session):
    """TestClient wired to the same transactional session as `db_session`,
    so requests made through it and direct ORM calls in the test see the
    same (uncommitted, rolled-back-at-teardown) data.
    """

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
