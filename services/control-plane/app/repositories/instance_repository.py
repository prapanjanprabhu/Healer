import uuid

from sqlalchemy import select

from app.db.models.application import Instance
from app.db.models.enums import InstanceStatus
from app.domain.state_machines import INSTANCE_TRANSITIONS, require_transition
from app.repositories.base import BaseRepository


class InstanceRepository(BaseRepository[Instance]):
    model = Instance

    def list_by_server(self, server_id: uuid.UUID) -> list[Instance]:
        stmt = select(Instance).where(Instance.server_id == server_id)
        return list(self.session.scalars(stmt).all())

    def transition(self, instance: Instance, target: InstanceStatus) -> Instance:
        require_transition(INSTANCE_TRANSITIONS, instance.status, target)
        instance.status = target
        self.session.flush()
        return instance
