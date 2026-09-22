from fastapi import FastAPI

from app.api.routes import gateway, health
from app.core.config import settings

app = FastAPI(
    title="Healer Gateway Manager",
    version=settings.service_version,
    description=(
        "Restricted, internal-only service. The only component permitted to "
        "render Nginx configuration and trigger a reload of the one central "
        "gateway. Never expose this service publicly or call it from the "
        "dashboard directly — see docs/security-boundaries.md."
    ),
)

app.include_router(health.router)
app.include_router(gateway.router)
