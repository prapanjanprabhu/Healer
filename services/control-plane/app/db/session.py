from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Request-scoped session: commits on a clean request, rolls back on
    exception. Repositories/services only flush — this is the single place
    that decides transaction boundaries. Tests override this dependency with
    a session bound to an outer transaction that's rolled back afterward
    (see tests/conftest.py), so nothing written by a test persists.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
