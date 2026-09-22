import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import engine


@pytest.fixture()
def db_session():
    """A Session bound to a single connection/transaction that is rolled
    back after the test, so tests never leave data behind in the shared
    dev/test Postgres instance and can run in any order.

    Requires the schema to already be migrated to head (`alembic upgrade
    head`) — this fixture does not create tables itself.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection)
    session: Session = session_factory()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
