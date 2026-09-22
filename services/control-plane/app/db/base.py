from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all Control Plane ORM models.

    No models are defined in Phase 1 — this exists so Alembic has a target
    metadata object to diff against once the schema (servers, applications,
    releases, instances, deployments, audit log) lands in a later phase.
    """
