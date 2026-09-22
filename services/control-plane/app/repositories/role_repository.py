from sqlalchemy import select

from app.db.models.user import Role
from app.repositories.base import BaseRepository


class RoleRepository(BaseRepository[Role]):
    model = Role

    def get_by_name(self, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        return self.session.scalars(stmt).first()

    def get_or_create(self, name: str) -> Role:
        role = self.get_by_name(name)
        if role is not None:
            return role
        return self.add(Role(name=name))
