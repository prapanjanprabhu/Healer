import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog
from app.db.models.deployment import Deployment
from app.db.models.enums import DeploymentStatus
from app.repositories.deployment_repository import DeploymentRepository


def transition_deployment(
    session: Session,
    deployment: Deployment,
    target: DeploymentStatus,
    actor_id: uuid.UUID | None = None,
) -> Deployment:
    """Move a deployment to a new status and record the change in the audit log.

    This is the only supported way to change `Deployment.status` — it enforces
    the state machine in app.domain.state_machines and keeps the audit trail
    consistent, which a route handler writing to the ORM directly could not
    guarantee.
    """
    repo = DeploymentRepository(session)
    previous = deployment.status
    repo.transition(deployment, target)
    session.add(
        AuditLog(
            actor_id=actor_id,
            action="deployment.transition",
            target_type="deployment",
            target_id=str(deployment.id),
            detail={"from": previous.value, "to": target.value},
            occurred_at=datetime.now(UTC),
        )
    )
    session.flush()
    return deployment
