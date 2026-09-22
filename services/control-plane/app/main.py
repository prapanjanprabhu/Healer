from fastapi import FastAPI

from app.api.routes import health
from app.core.config import settings

app = FastAPI(
    title="Healer Control Plane",
    version=settings.service_version,
    description=(
        "Source of truth for Healer: owns application/server state, issues jobs "
        "to the worker, holds agent connections, and is the only caller of the "
        "Gateway Manager. See docs/architecture.md."
    ),
)

app.include_router(health.router)


@app.get("/")
def root() -> dict:
    return {"service": settings.service_name, "status": "ok"}
