import uuid

from sqlalchemy import select

from app.db.models.server import EnrollmentToken
from app.repositories.base import BaseRepository


class EnrollmentTokenRepository(BaseRepository[EnrollmentToken]):
    model = EnrollmentToken

    def get_by_token_hash(self, token_hash: str) -> EnrollmentToken | None:
        stmt = select(EnrollmentToken).where(EnrollmentToken.token_hash == token_hash)
        return self.session.scalars(stmt).first()

    def list_by_server(self, server_id: uuid.UUID) -> list[EnrollmentToken]:
        stmt = select(EnrollmentToken).where(EnrollmentToken.server_id == server_id)
        return list(self.session.scalars(stmt).all())
