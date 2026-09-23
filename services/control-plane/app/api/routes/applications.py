import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_permission, verify_csrf
from app.db.models.application import Instance
from app.db.session import get_db
from app.domain.app_validation import validate_application
from app.domain.healer_yaml import HealerYamlParseError, parse_healer_yaml
from app.repositories.application_repository import ApplicationRepository
from app.schemas.applications import (
    ApplicationOut,
    ParseErrorOut,
    ParseYamlRequest,
    ParseYamlResponse,
    SecretKeyOut,
    SecretSetRequest,
    ValidationIssueOut,
    ValidationResponse,
)
from app.schemas.deployments import DeployTriggerResponse
from app.schemas.gateway import GatewaySyncResponse
from app.schemas.healer_yaml import HealerYamlV1
from app.services import (
    application_service,
    audit_service,
    deployment_service,
    gateway_service,
    secret_service,
)
from app.services.deployment_service import DeploymentSetupError

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("/parse-yaml", response_model=ParseYamlResponse)
def parse_yaml(
    payload: ParseYamlRequest, _current_user: CurrentUser = Depends(require_permission("view"))
) -> ParseYamlResponse:
    """Parses (but never saves) a pasted/uploaded healer.yaml — the
    dashboard wizard's "paste your healer.yaml" step, and a quick way to
    check a file is well-formed before filling in the form manually.
    """
    try:
        config = parse_healer_yaml(payload.yaml_text)
    except HealerYamlParseError as exc:
        return ParseYamlResponse(
            ok=False,
            errors=[ParseErrorOut(field=e["field"], message=e["message"]) for e in exc.errors],
        )
    return ParseYamlResponse(ok=True, config=config)


@router.get("", response_model=list[ApplicationOut])
def list_applications(
    db: Session = Depends(get_db), _current_user: CurrentUser = Depends(require_permission("view"))
) -> list[ApplicationOut]:
    return [ApplicationOut.from_model(a) for a in ApplicationRepository(db).list(limit=500)]


@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> ApplicationOut:
    application = ApplicationRepository(db).get(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")
    return ApplicationOut.from_model(application)


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    config: HealerYamlV1,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("deploy")),
    _csrf: None = Depends(verify_csrf),
) -> ApplicationOut:
    try:
        application = application_service.create_application(db, config)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a domain hostname in this config is already in use"
        ) from exc

    audit_service.record(
        db,
        actor_id=current_user.id,
        action="application.create",
        target_type="application",
        target_id=str(application.id),
        detail={"name": application.name, "adapter": config.adapter},
    )
    return ApplicationOut.from_model(application)


@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: uuid.UUID,
    config: HealerYamlV1,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("deploy")),
    _csrf: None = Depends(verify_csrf),
) -> ApplicationOut:
    application = ApplicationRepository(db).get(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")

    try:
        application_service.update_application(db, application, config)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a domain hostname in this config is already in use"
        ) from exc

    audit_service.record(
        db,
        actor_id=current_user.id,
        action="application.update",
        target_type="application",
        target_id=str(application.id),
    )
    return ApplicationOut.from_model(application)


@router.post("/{application_id}/validate", response_model=ValidationResponse)
async def validate_application_endpoint(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> ValidationResponse:
    """Runs every check in docs/app-validation.md against the application's
    currently-saved config. Never deploys, migrates, or touches Nginx.
    """
    application = ApplicationRepository(db).get(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")

    try:
        config = application_service.config_from_application(application)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"stored config no longer matches the current schema: {exc}",
        ) from exc

    issues = await validate_application(db, application, config)
    ok = not any(i.severity == "error" for i in issues)
    return ValidationResponse(
        ok=ok,
        issues=[
            ValidationIssueOut(field=i.field, severity=i.severity, message=i.message)
            for i in issues
        ],
    )


@router.post(
    "/{application_id}/deploy",
    response_model=DeployTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def deploy_application(
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("deploy")),
    _csrf: None = Depends(verify_csrf),
) -> DeployTriggerResponse:
    """Snapshots a release, runs it through venv/pip/check/migrate/
    collectstatic, and starts one Waitress instance on an automatically
    allocated port. Returns immediately (202) with the created ids — the
    actual Agent work continues in the background; poll
    `GET /deployments/{deployment_id}` for progress. See
    docs/app-deployment.md.
    """
    application = ApplicationRepository(db).get(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")

    try:
        config = application_service.config_from_application(application)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"stored config no longer matches the current schema: {exc}",
        ) from exc

    try:
        deployment = deployment_service.start_deployment(
            db, application, config, actor_id=current_user.id
        )
    except DeploymentSetupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    instance = db.scalars(
        select(Instance).where(Instance.release_id == deployment.release_id)
    ).one()

    audit_service.record(
        db,
        actor_id=current_user.id,
        action="application.deploy_triggered",
        target_type="application",
        target_id=str(application.id),
        detail={"deployment_id": str(deployment.id), "port": instance.port},
    )

    background_tasks.add_task(deployment_service.run_deployment, db, deployment.id)

    return DeployTriggerResponse(
        deployment_id=deployment.id,
        release_id=deployment.release_id,
        instance_id=instance.id,
        port=instance.port,
        service_name=instance.service_name,
    )


@router.post("/{application_id}/gateway/sync", response_model=GatewaySyncResponse)
async def sync_gateway_endpoint(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("deploy")),
    _csrf: None = Depends(verify_csrf),
) -> GatewaySyncResponse:
    """Re-renders and reloads this application's Nginx routing on the Gateway
    Manager from current Domain/Instance state, without running a new
    deployment. Useful after editing domain/certificate config, or to retry
    a routing sync that failed during a deploy. See docs/gateway-routing.md.
    """
    application = ApplicationRepository(db).get(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")

    result = await gateway_service.sync_gateway(db, application, actor_id=current_user.id)
    return GatewaySyncResponse(ok=result.ok, message=result.message)


@router.post("/{application_id}/secrets", status_code=status.HTTP_204_NO_CONTENT)
def set_secret(
    application_id: uuid.UUID,
    payload: SecretSetRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("deploy")),
    _csrf: None = Depends(verify_csrf),
) -> None:
    application = ApplicationRepository(db).get(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")

    secret_service.set_secret(db, application_id, payload.key, payload.value)
    # Never include the value — see app/services/secret_service.py.
    audit_service.record(
        db,
        actor_id=current_user.id,
        action="application.secret_set",
        target_type="application",
        target_id=str(application_id),
        detail={"key": payload.key},
    )


@router.get("/{application_id}/secrets", response_model=list[SecretKeyOut])
def list_secrets(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_permission("view")),
) -> list[SecretKeyOut]:
    records = secret_service.list_secret_keys(db, application_id)
    return [
        SecretKeyOut(key=r.key, created_at=r.created_at, updated_at=r.updated_at) for r in records
    ]


@router.delete("/{application_id}/secrets/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret(
    application_id: uuid.UUID,
    key: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission("deploy")),
    _csrf: None = Depends(verify_csrf),
) -> None:
    if not secret_service.delete_secret(db, application_id, key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="secret not found")
    audit_service.record(
        db,
        actor_id=current_user.id,
        action="application.secret_deleted",
        target_type="application",
        target_id=str(application_id),
        detail={"key": key},
    )
