import uuid

from sqlalchemy import select

from app.db.models.agent import AgentCommand
from app.db.models.enums import AgentCommandStatus
from app.domain.state_machines import AGENT_COMMAND_TRANSITIONS, require_transition
from app.repositories.base import BaseRepository


class AgentCommandRepository(BaseRepository[AgentCommand]):
    model = AgentCommand

    def get_by_idempotency_key(self, idempotency_key: str) -> AgentCommand | None:
        stmt = select(AgentCommand).where(AgentCommand.idempotency_key == idempotency_key)
        return self.session.scalars(stmt).first()

    def list_by_agent(self, agent_id: uuid.UUID, limit: int = 100) -> list[AgentCommand]:
        stmt = (
            select(AgentCommand)
            .where(AgentCommand.agent_id == agent_id)
            .order_by(AgentCommand.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def list_pending_for_agent(self, agent_id: uuid.UUID) -> list[AgentCommand]:
        stmt = select(AgentCommand).where(
            AgentCommand.agent_id == agent_id, AgentCommand.status == AgentCommandStatus.PENDING
        )
        return list(self.session.scalars(stmt).all())

    def transition(self, command: AgentCommand, target: AgentCommandStatus) -> AgentCommand:
        require_transition(AGENT_COMMAND_TRANSITIONS, command.status, target)
        command.status = target
        self.session.flush()
        return command
