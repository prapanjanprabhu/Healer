from sqlalchemy import select

from app.db.models.application import Application
from app.repositories.base import BaseRepository


class ApplicationRepository(BaseRepository[Application]):
    model = Application

    def get_by_slug(self, slug: str) -> Application | None:
        stmt = select(Application).where(Application.slug == slug)
        return self.session.scalars(stmt).first()
