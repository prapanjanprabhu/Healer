import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    agents,
    applications,
    audit,
    auth,
    deployments,
    health,
    logs,
    metrics,
    notifications,
    servers,
    users,
    ws,
)
from app.core.config import settings
from app.services import health_monitor, metrics_retention, reconcile_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    reconciled = await asyncio.to_thread(reconcile_service.reconcile_on_startup)
    if reconciled:
        logger.warning("startup recovery: reconciled %d stuck deployment(s)", reconciled)

    tasks = []
    if settings.health_monitor_enabled:
        tasks.append(asyncio.create_task(health_monitor.run_forever()))
        tasks.append(asyncio.create_task(metrics_retention.run_forever()))
        logger.info("health monitor and metrics retention loops started")
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
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
app.include_router(metrics.router)
app.include_router(logs.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(ws.router)


@app.get("/")
def root() -> dict:
    return {"service": settings.service_name, "status": "ok"}
