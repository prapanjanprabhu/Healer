"""Control Plane restart recovery (Phase 15) — reconciles state a crashed
or restarted process left behind. Runs once at startup, before the app
accepts any request (see app/main.py's lifespan): nothing else could have
created a fresh IN_PROGRESS deployment by that point, so every one found
here was left behind by whatever process held it before this one started —
a deploy/scale/release switch that was running when the Control Plane
stopped can never be resumed (the in-memory command-completion state
command_service relies on is gone), so the safe, honest outcome is to mark
it failed rather than leave it "in progress" forever with nothing left
actually driving it, and to free the application's operation lock
immediately rather than wait for lock_service's own stale-lock timeout.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.application import Instance
from app.db.models.deployment import Deployment, DeploymentLog
from app.db.models.enums import DeploymentStatus, InstanceStatus
from app.db.session import SessionLocal
from app.repositories.instance_repository import InstanceRepository
from app.services import lock_service
from app.services.deployment_service import transition_deployment

logger = logging.getLogger(__name__)

STUCK_DEPLOYMENT_REASON = "control plane restarted while this operation was in progress"
STUCK_INSTANCE_REASON = "control plane restarted while this instance was mid-transition"

# States only ever set by a background task that is actively driving the
# instance toward its next state (STARTING -> RUNNING, RESTARTING ->
# RUNNING, DRAINING -> STOPPED — see app/domain/state_machines.py). If the
# process restarts, that task is gone and nothing will ever move the
# instance out of this state again; discovered as a genuine orphaned-state
# bug during Phase 15 (an instance stuck in STARTING for hours after a
# container restart interrupted self-healing's _replace mid-flight — see
# docs/release.md's Phase 15 notes) — health_monitor.tick() only ever polls
# RUNNING and UNHEALTHY instances, so a STARTING/RESTARTING/DRAINING
# instance was invisible to it forever, not just until the next tick.
_TRANSIENT_INSTANCE_STATUSES = (
    InstanceStatus.STARTING,
    InstanceStatus.RESTARTING,
    InstanceStatus.DRAINING,
)


def reconcile_on_startup() -> int:
    session = SessionLocal()
    try:
        return reconcile_stuck_deployments(session) + reconcile_stuck_instances(session)
    finally:
        session.close()


def reconcile_stuck_deployments(session: Session) -> int:
    stuck = session.scalars(
        select(Deployment).where(Deployment.status == DeploymentStatus.IN_PROGRESS)
    ).all()
    for deployment in stuck:
        deployment.failure_reason = STUCK_DEPLOYMENT_REASON
        session.add(
            DeploymentLog(
                deployment_id=deployment.id, level="error", message=STUCK_DEPLOYMENT_REASON
            )
        )
        transition_deployment(session, deployment, DeploymentStatus.FAILED)
        lock_service.release(session, deployment.application_id)
        logger.warning(
            "reconciled stuck deployment %s (application %s) after restart",
            deployment.id,
            deployment.application_id,
        )
    session.commit()
    return len(stuck)


def reconcile_stuck_instances(session: Session) -> int:
    stuck = session.scalars(
        select(Instance).where(Instance.status.in_(_TRANSIENT_INSTANCE_STATUSES))
    ).all()
    for instance in stuck:
        instance.failure_reason = STUCK_INSTANCE_REASON
        InstanceRepository(session).transition(instance, InstanceStatus.FAILED)
        logger.warning(
            "reconciled stuck instance %s (port %d, was %s) after restart",
            instance.id,
            instance.port,
            instance.status,
        )
    session.commit()
    return len(stuck)
