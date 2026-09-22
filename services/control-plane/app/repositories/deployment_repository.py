import uuid

from sqlalchemy import select

from app.db.models.deployment import Deployment
from app.db.models.enums import DeploymentStatus
from app.domain.state_machines import DEPLOYMENT_TRANSITIONS, require_transition
from app.repositories.base import BaseRepository


class DeploymentRepository(BaseRepository[Deployment]):
    model = Deployment

    def latest_for_application(self, application_id: uuid.UUID) -> Deployment | None:
        stmt = (
            select(Deployment)
            .where(Deployment.application_id == application_id)
            .order_by(Deployment.created_at.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def transition(self, deployment: Deployment, target: DeploymentStatus) -> Deployment:
        require_transition(DEPLOYMENT_TRANSITIONS, deployment.status, target)
        deployment.status = target
        self.session.flush()
        return deployment
