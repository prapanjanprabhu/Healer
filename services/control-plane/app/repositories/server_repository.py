from sqlalchemy import select

from app.db.models.server import Server
from app.repositories.base import BaseRepository


class ServerRepository(BaseRepository[Server]):
    model = Server

    def get_by_hostname(self, hostname: str) -> Server | None:
        stmt = select(Server).where(Server.hostname == hostname)
        return self.session.scalars(stmt).first()
