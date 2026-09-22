import uuid

from sqlalchemy import select

from app.db.models.agent import Agent
from app.repositories.base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    model = Agent

    def get_by_server_id(self, server_id: uuid.UUID) -> Agent | None:
        stmt = select(Agent).where(Agent.server_id == server_id)
        return self.session.scalars(stmt).first()

    def get_by_credential_hash(self, credential_hash: str) -> Agent | None:
        stmt = select(Agent).where(Agent.credential_hash == credential_hash)
        return self.session.scalars(stmt).first()
