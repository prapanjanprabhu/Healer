"""Import every model module so `Base.metadata` is fully populated before
Alembic autogenerate (or `Base.metadata.create_all`) runs.
"""

from app.db.models.agent import Agent, AgentCommand, AgentConnection, AgentEvent
from app.db.models.application import Application, Configuration, Instance, Release, Source
from app.db.models.audit import AuditLog
from app.db.models.deployment import Deployment, DeploymentLog, DeploymentStep
from app.db.models.domain import Domain, UpstreamGroup, UpstreamInstance
from app.db.models.health import HealthCheck, HealthCheckResult
from app.db.models.metrics import MetricsSnapshot
from app.db.models.notification import Notification
from app.db.models.secret import SecretRecord
from app.db.models.server import EnrollmentToken, Server
from app.db.models.user import RefreshSession, Role, User, UserRole

__all__ = [
    "Agent",
    "AgentCommand",
    "AgentConnection",
    "AgentEvent",
    "Application",
    "Configuration",
    "Instance",
    "Release",
    "Source",
    "AuditLog",
    "Deployment",
    "DeploymentLog",
    "DeploymentStep",
    "Domain",
    "UpstreamGroup",
    "UpstreamInstance",
    "HealthCheck",
    "HealthCheckResult",
    "MetricsSnapshot",
    "Notification",
    "SecretRecord",
    "EnrollmentToken",
    "Server",
    "RefreshSession",
    "Role",
    "User",
    "UserRole",
]
