import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission, verify_csrf
from app.db.models.application import Instance, Release
from app.db.models.deployment import DeploymentLog, DeploymentStep
from app.db.models.enums import DeploymentStatus
from app.db.session import get_db
from app.repositories.deployment_repository import DeploymentRepository
from app.schemas.deployments import (
    DeploymentDetailOut,
    DeploymentInstanceOut,
    DeploymentLogOut,
    DeploymentStepOut,
)
from app.services.deployment_service import transition_deployment

router = APIRouter(prefix="/deployments", tags=["deployments"])


@router.get("", dependencies=[Depends(require_permission("view"))])
def list_deployments(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": str(deployment.id),
            "application_id": str(deployment.application_id),
            "status": deployment.status.value,
        }
        for deployment in DeploymentRepository(db).list()
    ]


@router.get("/{deployment_id}", response_model=DeploymentDetailOut)
def get_deployment(
    deployment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> DeploymentDetailOut:
    """Polling target for the dashboard while a deploy runs in the
    background — see `POST /applications/{id}/deploy`. Steps/logs are
    written incrementally as each Agent command finishes, so this reflects
    live progress, not just a final result.
    """
    deployment = DeploymentRepository(db).get(deployment_id)
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="deployment not found")

    release = db.get(Release, deployment.release_id)
    instances = db.scalars(
        select(Instance).where(Instance.deployment_id == deployment.id).order_by(Instance.port)
    ).all()

    steps = db.scalars(
        select(DeploymentStep)
        .where(DeploymentStep.deployment_id == deployment.id)
        .order_by(DeploymentStep.created_at)
    ).all()
    logs = db.scalars(
        select(DeploymentLog)
        .where(DeploymentLog.deployment_id == deployment.id)
        .order_by(DeploymentLog.created_at)
    ).all()

    return DeploymentDetailOut(
        id=deployment.id,
        application_id=deployment.application_id,
        release_id=deployment.release_id,
        release_version=release.ref if release else "",
        status=deployment.status.value,
        kind=deployment.kind,
        failure_reason=deployment.failure_reason,
        instances=[
            DeploymentInstanceOut(
                id=instance.id,
                server_id=instance.server_id,
                port=instance.port,
                service_name=instance.service_name,
                status=instance.status.value,
            )
            for instance in instances
        ],
        steps=[
            DeploymentStepOut(
                name=s.name,
                status=s.status.value,
                started_at=s.started_at,
                finished_at=s.finished_at,
            )
            for s in steps
        ],
        logs=[
            DeploymentLogOut(
                step_id=log_.step_id,
                level=log_.level,
                message=log_.message,
                created_at=log_.created_at,
            )
            for log_ in logs
        ],
        created_at=deployment.created_at,
        updated_at=deployment.updated_at,
    )


@router.post("/{deployment_id}/actions/deploy")
def start_deployment(
    deployment_id: uuid.UUID,
    db: Session = Depends(get_db),
    # Order matters: resolving auth before CSRF means an unauthenticated
    # request gets 401 (not authenticated) rather than 403 (CSRF mismatch) —
    # CSRF is only meaningful once we know there's a session to protect.
    current_user: CurrentUser = Depends(require_permission("deploy")),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """Move a pending deployment to in-progress.

    Demonstrates permission-gated, audited mutation on top of the Phase 2
    schema — the actual deploy pipeline (agent commands, instance rollout)
    is implemented in a later phase.
    """
    deployment = DeploymentRepository(db).get(deployment_id)
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="deployment not found")

    transition_deployment(db, deployment, DeploymentStatus.IN_PROGRESS, actor_id=current_user.id)
    return {"id": str(deployment.id), "status": deployment.status.value}
