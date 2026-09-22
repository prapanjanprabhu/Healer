import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.agent import Agent
from app.db.models.application import Application, Release
from app.db.models.enums import AdapterType, ReleaseStatus, ServerOS, ServerStatus
from app.db.models.server import Server


def make_server(session: Session, **overrides) -> Server:
    defaults = dict(
        name="test-server",
        hostname=f"srv-{uuid.uuid4().hex[:8]}.example.internal",
        os=ServerOS.LINUX,
        status=ServerStatus.ACTIVE,
    )
    defaults.update(overrides)
    server = Server(**defaults)
    session.add(server)
    session.flush()
    return server


def make_agent(session: Session, server: Server | None = None, **overrides) -> Agent:
    server = server or make_server(session)
    defaults = dict(server_id=server.id, agent_version="0.1.0-dev")
    defaults.update(overrides)
    agent = Agent(**defaults)
    session.add(agent)
    session.flush()
    return agent


def make_application(session: Session, **overrides) -> Application:
    defaults = dict(
        name="test-app",
        slug=f"test-app-{uuid.uuid4().hex[:8]}",
        adapter_type=AdapterType.LINUX_DOCKER,
    )
    defaults.update(overrides)
    application = Application(**defaults)
    session.add(application)
    session.flush()
    return application


def make_release(session: Session, application: Application | None = None, **overrides) -> Release:
    application = application or make_application(session)
    defaults = dict(application_id=application.id, ref="v1", status=ReleaseStatus.READY)
    defaults.update(overrides)
    release = Release(**defaults)
    session.add(release)
    session.flush()
    return release


def utcnow() -> datetime:
    return datetime.now(UTC)
