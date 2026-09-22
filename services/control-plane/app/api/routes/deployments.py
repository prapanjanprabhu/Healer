import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission, verify_csrf
from app.db.models.enums import DeploymentStatus
from app.db.session import get_db
from app.repositories.deployment_repository import DeploymentRepository
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
