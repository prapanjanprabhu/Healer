import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    agents,
    applications,
    auth,
    deployments,
    health,
    notifications,
    servers,
    ws,
)
from app.core.config import settings
from app.services import health_monitor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = None
    if settings.health_monitor_enabled:
        task = asyncio.create_task(health_monitor.run_forever())
        logger.info("health monitor started")
    yield
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Healer Control Plane",
    version=settings.service_version,
    description=(
        "Source of truth for Healer: owns application/server state, issues jobs "
        "to the worker, holds agent connections, and is the only caller of the "
        "Gateway Manager. See docs/architecture.md."
    ),
    lifespan=lifespan,
)

# The dashboard runs on a different origin (different port) in dev and any
# real deployment, and needs cookies sent — credentials require an explicit
# origin allowlist, never "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.dashboard_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(deployments.router)
app.include_router(servers.router)
app.include_router(agents.router)
app.include_router(applications.router)
app.include_router(notifications.router)
app.include_router(ws.router)


@app.get("/")
def root() -> dict:
    return {"service": settings.service_name, "status": "ok"}
