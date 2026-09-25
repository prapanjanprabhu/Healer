import uuid
from datetime import UTC, datetime
from pathlib import PureWindowsPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.application import Application, Instance, Release, Source
from app.db.models.audit import AuditLog
from app.db.models.deployment import Deployment, DeploymentLog, DeploymentStep
from app.db.models.enums import (
    AgentCommandType,
    AgentStatus,
    DeploymentStatus,
    DeploymentStepStatus,
    InstanceStatus,
    ReleaseStatus,
)
from app.repositories.agent_repository import AgentRepository
from app.repositories.deployment_repository import DeploymentRepository
from app.repositories.instance_repository import InstanceRepository
from app.schemas.healer_yaml import HealerYamlV1
from app.services import (
    application_service,
    command_service,
    gateway_service,
    lock_service,
    secret_service,
)


def transition_deployment(
    session: Session,
    deployment: Deployment,
    target: DeploymentStatus,
    actor_id: uuid.UUID | None = None,
) -> Deployment:
    """Move a deployment to a new status and record the change in the audit log.

    This is the only supported way to change `Deployment.status` — it enforces
    the state machine in app.domain.state_machines and keeps the audit trail
    consistent, which a route handler writing to the ORM directly could not
    guarantee.
    """
    repo = DeploymentRepository(session)
    previous = deployment.status
    repo.transition(deployment, target)
    session.add(
        AuditLog(
            actor_id=actor_id,
            action="deployment.transition",
            target_type="deployment",
            target_id=str(deployment.id),
            detail={"from": previous.value, "to": target.value},
            occurred_at=datetime.now(UTC),
        )
    )
    session.flush()
    return deployment


class DeploymentSetupError(Exception):
    """A problem that prevents even starting a deployment attempt (no
    connected Agent, unsupported adapter, no free port left in the
    configured range) — surfaced as a 4xx by the route, never turned into a
    Deployment row that immediately fails.
    """


def _service_name(slug: str, port: int) -> str:
    return f"Healer-{slug}-{port}"


def start_deployment(
    session: Session, application: Application, config: HealerYamlV1, *, actor_id: uuid.UUID | None
) -> Deployment:
    """Allocates a port, creates the Release/Instance/Deployment rows, and
    moves the deployment to IN_PROGRESS. The real work (agent commands)
    happens afterward in `run_deployment`, run as a FastAPI BackgroundTask
    against this same request-scoped session — see docs/app-deployment.md
    for why that's safe (dependency cleanup runs after background tasks,
    not before).

    This is the one-time bootstrap deploy only (first release, exactly one
    instance) — once `application.active_release_id` is set, every
    subsequent update goes through the health-gated blue-green flow
    instead (`POST /applications/{id}/releases` — see
    app/services/release_service.py), never this single-instance path.
    """
    if application.active_release_id is not None:
        raise DeploymentSetupError(
            "application is already deployed — use POST /applications/{id}/releases "
            "for a blue-green update, or /rollback to restore a previous release"
        )
    if config.adapter == "windows-waitress-service" and config.windows is None:
        raise DeploymentSetupError("adapter windows-waitress-service requires a windows: section")
    if config.adapter == "linux-docker" and config.linux is None:
        raise DeploymentSetupError("adapter linux-docker requires a linux: section")
    if config.adapter not in ("windows-waitress-service", "linux-docker"):
        raise DeploymentSetupError(f"adapter {config.adapter!r} is not implemented")
    if config.server_id is None:
        raise DeploymentSetupError("no target server selected")

    agent = AgentRepository(session).get_by_server_id(config.server_id)
    if agent is None or agent.status != AgentStatus.CONNECTED:
        raise DeploymentSetupError("the target server's Agent is not currently connected")

    source = session.scalars(select(Source).where(Source.application_id == application.id)).first()
    if source is None:
        raise DeploymentSetupError("application has no source configured")

    release_version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    release = Release(
        application_id=application.id,
        source_id=source.id,
        ref=release_version,
        status=ReleaseStatus.PENDING,
    )
    session.add(release)
    session.flush()

    instance = _allocate_instance(
        session,
        application=application,
        release=release,
        server_id=config.server_id,
        port_start=config.ports.start,
        port_end=config.ports.end,
    )

    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.PENDING,
        instance_count=1,
        created_by=actor_id,
    )
    session.add(deployment)
    session.flush()
    instance.deployment_id = deployment.id

    transition_deployment(session, deployment, DeploymentStatus.IN_PROGRESS, actor_id=actor_id)
    session.commit()
    return deployment


def _allocate_instance(
    session: Session,
    *,
    application: Application,
    release: Release,
    server_id: uuid.UUID,
    port_start: int,
    port_end: int,
) -> Instance:
    """Transactional port allocation: try each port in the configured range,
    relying on the `uq_instances_server_id_port` unique constraint to catch
    a concurrent deploy racing for the same port. Each attempt runs in its
    own SAVEPOINT so a collision only unwinds that one attempt, not the
    Release row already created in this same transaction.
    """
    for port in range(port_start, port_end + 1):
        savepoint = session.begin_nested()
        try:
            instance = Instance(
                application_id=application.id,
                release_id=release.id,
                server_id=server_id,
                port=port,
                status=InstanceStatus.PENDING,
                service_name=_service_name(application.slug, port),
            )
            session.add(instance)
            session.flush()
        except IntegrityError:
            savepoint.rollback()
            continue
        else:
            savepoint.commit()
            return instance
    raise DeploymentSetupError(
        f"no free port available in range {port_start}-{port_end} on this server"
    )


_STEP_STATUS_MAP = {
    "succeeded": DeploymentStepStatus.SUCCEEDED,
    "failed": DeploymentStepStatus.FAILED,
    "skipped": DeploymentStepStatus.SKIPPED,
}


def _persist_agent_outcome(session: Session, deployment: Deployment, command) -> bool:
    """Turns one finished AgentCommand (deploy_release or start_instance)
    into DeploymentStep/DeploymentLog rows and returns whether it succeeded
    overall. Always writes *something* — even a bare timeout or a
    structural Agent error becomes a visible log line — so a deployment
    never fails silently.
    """
    if command.status.value not in ("succeeded", "failed"):
        session.add(
            DeploymentLog(
                deployment_id=deployment.id,
                level="error",
                message=(
                    "the Agent did not respond in time " f"(command status: {command.status.value})"
                ),
            )
        )
        session.flush()
        return False

    if command.error:
        session.add(
            DeploymentLog(deployment_id=deployment.id, level="error", message=command.error)
        )
        session.flush()
        return False

    result = command.result or {}
    now = datetime.now(UTC)
    for step in result.get("steps", []):
        step_status = _STEP_STATUS_MAP.get(step.get("status"), DeploymentStepStatus.FAILED)
        step_row = DeploymentStep(
            deployment_id=deployment.id,
            name=step.get("name", "unknown"),
            status=step_status,
            started_at=now,
            finished_at=now,
        )
        session.add(step_row)
        session.flush()
        session.add(
            DeploymentLog(
                deployment_id=deployment.id,
                step_id=step_row.id,
                level="error" if step_status == DeploymentStepStatus.FAILED else "info",
                message=step.get("message", ""),
            )
        )
    session.flush()
    return bool(result.get("ok", False))


def _build_deploy_release_payload(
    application: Application, release: Release, config: HealerYamlV1
) -> dict:
    payload: dict[str, Any] = {
        "adapter": config.adapter,
        "app_slug": application.slug,
        "release_version": release.ref,
        "source": {
            "type": config.source.type,
            "location": config.source.location,
            "ref": config.source.ref,
        },
    }
    if config.adapter == "windows-waitress-service" and config.windows is not None:
        payload["windows"] = config.windows.model_dump()
    elif config.adapter == "linux-docker" and config.linux is not None:
        payload["linux"] = config.linux.model_dump()
    return payload


def _shared_log_dir(release_dir: str) -> str:
    """`release_dir` is `<app_dir>\\releases\\<version>` — the shared log
    directory the Agent maintains alongside it is `<app_dir>\\shared\\logs`.
    Pure string manipulation (no filesystem access, no OS-specific env
    lookup): the Control Plane never learns the Agent's actual data-dir
    root any other way, so it derives the sibling path instead. Windows
    adapter only — a Docker container has no equivalent release directory
    (see log_service.py, which reads container logs through the Agent's
    `docker logs` path instead of a shared log file for linux-docker).
    """
    release_path = PureWindowsPath(release_dir)
    app_dir = release_path.parent.parent
    return str(app_dir / "shared" / "logs")


def _build_start_instance_payload(
    session: Session, release: Release, instance: Instance, config: HealerYamlV1
) -> dict:
    payload: dict[str, Any] = {
        "adapter": config.adapter,
        "service_name": instance.service_name,
        "port": instance.port,
    }
    if config.adapter == "windows-waitress-service" and config.windows is not None:
        windows = config.windows
        release_dir = release.release_dir or ""
        payload.update(
            {
                "release_dir": release.release_dir,
                "venv_python": release.venv_python,
                "wsgi_module": windows.wsgi_module,
                "host": "127.0.0.1",
                "log_dir": _shared_log_dir(release_dir),
            }
        )
    elif config.adapter == "linux-docker" and config.linux is not None:
        linux = config.linux
        env = dict(linux.env)
        env.update(secret_service.get_secret_dict(session, instance.application_id))
        payload["linux"] = {
            "image_ref": release.image_ref,
            "internal_port": linux.internal_port,
            "env": env,
            "cpu_limit": linux.cpu_limit,
            "memory_limit_mb": linux.memory_limit_mb,
        }
    return payload


def _build_stop_instance_payload(instance: Instance, config: HealerYamlV1) -> dict:
    return {"adapter": config.adapter, "service_name": instance.service_name}


async def run_deployment(session: Session, deployment_id: uuid.UUID, lock_token: datetime) -> None:
    """The actual deploy pipeline: deploy_release then start_instance on the
    target Agent, persisting every step. Runs as a FastAPI BackgroundTask
    against the triggering request's own session — see `start_deployment`.

    Commits at each checkpoint (not just flushes) so a concurrent
    `GET /deployments/{id}` poll — a different request, hence a different
    session/connection — can see progress as it happens rather than only
    once this whole function returns. This mirrors command_service's own
    documented mid-function commits, for the same cross-session-visibility
    reason.
    """
    deployment = DeploymentRepository(session).get(deployment_id)
    if deployment is None:
        return
    try:
        release = session.get(Release, deployment.release_id)
        application = session.get(Application, deployment.application_id)
        if release is None or application is None:
            return
        instance = session.scalars(
            select(Instance).where(Instance.release_id == release.id)
        ).first()
        if instance is None:
            return

        config = application_service.config_from_application(application)
        agent = AgentRepository(session).get_by_server_id(instance.server_id)
        if agent is None:
            session.add(
                DeploymentLog(
                    deployment_id=deployment.id,
                    level="error",
                    message="the target server's Agent disappeared before deployment could run",
                )
            )
            transition_deployment(session, deployment, DeploymentStatus.FAILED)
            session.commit()
            return

        release.status = ReleaseStatus.BUILDING
        session.commit()

        deploy_payload = _build_deploy_release_payload(application, release, config)
        deploy_command = await command_service.submit_command_and_wait(
            session,
            agent,
            AgentCommandType.DEPLOY_RELEASE,
            deploy_payload,
            idempotency_key=f"deploy-release:{deployment.id}",
            ttl_seconds=600,
            wait_seconds=480.0,
        )
        deploy_ok = _persist_agent_outcome(session, deployment, deploy_command)
        if deploy_ok:
            result = deploy_command.result or {}
            release.release_dir = result.get("release_dir")
            release.venv_python = result.get("venv_python")
            release.image_ref = result.get("image_ref")
            release.status = ReleaseStatus.READY
        else:
            release.status = ReleaseStatus.FAILED
        session.commit()

        if not deploy_ok:
            InstanceRepository(session).transition(instance, InstanceStatus.FAILED)
            transition_deployment(session, deployment, DeploymentStatus.FAILED)
            session.commit()
            return

        InstanceRepository(session).transition(instance, InstanceStatus.STARTING)
        session.commit()

        start_payload = _build_start_instance_payload(session, release, instance, config)
        start_command = await command_service.submit_command_and_wait(
            session,
            agent,
            AgentCommandType.START_INSTANCE,
            start_payload,
            idempotency_key=f"start-instance:{instance.id}",
            # The "permissions" step recursively grants the low-privilege
            # service account read+execute on the base Python installation
            # (icacls ... /T) — a one-time-per-interpreter cost that can take
            # well over a minute on a large stdlib/site-packages tree, so this
            # needs real headroom, not the quick round trip start_instance's
            # other steps would otherwise suggest.
            ttl_seconds=200,
            wait_seconds=180.0,
        )
        start_ok = _persist_agent_outcome(session, deployment, start_command)
        if start_ok:
            InstanceRepository(session).transition(instance, InstanceStatus.RUNNING)
            transition_deployment(session, deployment, DeploymentStatus.SUCCEEDED)
            application.active_release_id = release.id
            session.commit()
            if config.domain is not None:
                await _sync_gateway_step(session, deployment, application)
        else:
            InstanceRepository(session).transition(instance, InstanceStatus.FAILED)
            transition_deployment(session, deployment, DeploymentStatus.FAILED)
            session.commit()
    finally:
        lock_service.release(session, deployment.application_id, lock_token)


async def _sync_gateway_step(
    session: Session, deployment: Deployment, application: Application
) -> None:
    """Best-effort Nginx routing sync after a successful deploy — recorded as
    its own visible DeploymentStep/DeploymentLog, but never able to flip the
    Deployment (already SUCCEEDED) back to FAILED: the deployed instance is
    genuinely running regardless of whether the Gateway Manager could be
    reached, and routing problems are a separate, always-visible concern
    (see gateway_service.sync_gateway).
    """
    result = await gateway_service.sync_gateway(
        session, application, actor_id=deployment.created_by
    )
    now = datetime.now(UTC)
    step = DeploymentStep(
        deployment_id=deployment.id,
        name="gateway_sync",
        status=DeploymentStepStatus.SUCCEEDED if result.ok else DeploymentStepStatus.FAILED,
        started_at=now,
        finished_at=now,
    )
    session.add(step)
    session.flush()
    session.add(
        DeploymentLog(
            deployment_id=deployment.id,
            step_id=step.id,
            level="info" if result.ok else "error",
            message=result.message
            or ("gateway routing updated" if result.ok else "gateway sync failed"),
        )
    )
    session.commit()
