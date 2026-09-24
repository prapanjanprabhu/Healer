"""Manual replica scaling — see docs/scaling.md.

Reuses the Deployment/DeploymentStep/DeploymentLog tables from the deploy
pipeline: a scale operation is a Deployment against the application's
current release that only runs start_instance/stop_instance, never
deploy_release — it changes how many copies of the already-deployed release
are running, not the release itself. `Deployment.instance_count`, unused
since Phase 7, is finally the scale target this operation is reconciling
towards.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.application import Application, Instance, Release
from app.db.models.deployment import Deployment, DeploymentLog, DeploymentStep
from app.db.models.enums import (
    AgentCommandType,
    AgentStatus,
    DeploymentStatus,
    DeploymentStepStatus,
    InstanceStatus,
    ReleaseStatus,
)
from app.db.models.health import HealthCheck, HealthCheckResult
from app.db.models.server import Server
from app.repositories.agent_repository import AgentRepository
from app.repositories.deployment_repository import DeploymentRepository
from app.repositories.instance_repository import InstanceRepository
from app.schemas.healer_yaml import HealerYamlV1
from app.services import (
    application_service,
    command_service,
    gateway_service,
    health_check_service,
    lock_service,
)
from app.services.deployment_service import (
    DeploymentSetupError,
    _allocate_instance,
    _build_start_instance_payload,
    _build_stop_instance_payload,
    transition_deployment,
)

# A live-traffic instance selected for scale-down is removed from Nginx
# (via a gateway sync marking it DRAINING, which excludes it from the
# upstream) and then given this long to let requests already in flight on
# its existing connections finish naturally before it's hard-stopped. There
# is no active-connection-count signal available (would need a new Agent
# capability), so this is a fixed grace period, not a real drain-complete
# detection — see docs/scaling.md's "Known simplifications".
DEFAULT_DRAIN_TIMEOUT_SECONDS = 15

_LIVE_STATUSES = (
    InstanceStatus.PENDING,
    InstanceStatus.STARTING,
    InstanceStatus.RUNNING,
    InstanceStatus.UNHEALTHY,
)

_STEP_STATUS_MAP = {
    "succeeded": DeploymentStepStatus.SUCCEEDED,
    "failed": DeploymentStepStatus.FAILED,
    "skipped": DeploymentStepStatus.SKIPPED,
}


class ScaleSetupError(Exception):
    """A problem that prevents even starting a scale attempt — surfaced as a
    4xx by the route, never turned into a Deployment row that immediately
    fails.
    """


@dataclass
class InstanceView:
    id: uuid.UUID
    port: int
    server_id: uuid.UUID
    server_name: str
    status: str
    release_version: str
    service_name: str | None
    healthy: bool | None
    response_time_ms: int | None
    last_checked_at: datetime | None
    failure_reason: str | None
    healing_attempts: int
    created_at: datetime


def _live_instances(session: Session, application_id: uuid.UUID) -> list[Instance]:
    """Instances that currently occupy a "slot" toward the replica count —
    excludes DRAINING/STOPPED/FAILED (already leaving, or gone)."""
    return list(
        session.scalars(
            select(Instance).where(
                Instance.application_id == application_id,
                Instance.status.in_(_LIVE_STATUSES),
            )
        ).all()
    )


def start_scale(
    session: Session, application: Application, target: int, *, actor_id: uuid.UUID | None
) -> Deployment:
    """Validates the target against [min_replicas, max_replicas], creates a
    Deployment row against the application's current release, and moves it
    to IN_PROGRESS. The actual work happens in `run_scale`, a FastAPI
    BackgroundTask — mirrors deployment_service.start_deployment. Caller
    must already hold the application's operation lock.
    """
    if target < application.min_replicas or target > application.max_replicas:
        raise ScaleSetupError(
            f"desired replica count {target} is outside the allowed range "
            f"[{application.min_replicas}, {application.max_replicas}]"
        )
    if application.server_id is None:
        raise ScaleSetupError("no target server selected")

    agent = AgentRepository(session).get_by_server_id(application.server_id)
    if agent is None or agent.status != AgentStatus.CONNECTED:
        raise ScaleSetupError("the target server's Agent is not currently connected")

    release = session.scalars(
        select(Release)
        .where(Release.application_id == application.id, Release.status == ReleaseStatus.READY)
        .order_by(Release.created_at.desc())
    ).first()
    if release is None:
        raise ScaleSetupError("application has no successfully deployed release to scale")

    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.PENDING,
        instance_count=target,
        created_by=actor_id,
    )
    session.add(deployment)
    session.flush()
    transition_deployment(session, deployment, DeploymentStatus.IN_PROGRESS, actor_id=actor_id)
    application.desired_replicas = target
    session.commit()
    return deployment


def _log(session: Session, deployment: Deployment, level: str, message: str) -> None:
    session.add(DeploymentLog(deployment_id=deployment.id, level=level, message=message))
    session.commit()


def _persist_instance_command_outcome(
    session: Session, deployment: Deployment, command, *, port: int
) -> bool:
    """Same shape as deployment_service._persist_agent_outcome, but for a
    Deployment that spans multiple instances at once (a scale operation) —
    step names are prefixed with the port so a multi-instance scale's step
    list stays legible instead of N identically-named "permissions" steps.
    """
    if command.status.value not in ("succeeded", "failed"):
        _log(
            session,
            deployment,
            "error",
            f"port {port}: the Agent did not respond in time "
            f"(command status: {command.status.value})",
        )
        return False
    if command.error:
        _log(session, deployment, "error", f"port {port}: {command.error}")
        return False

    result = command.result or {}
    now = datetime.now(UTC)
    for step in result.get("steps", []):
        step_status = _STEP_STATUS_MAP.get(step.get("status"), DeploymentStepStatus.FAILED)
        step_row = DeploymentStep(
            deployment_id=deployment.id,
            name=f"port_{port}_{step.get('name', 'unknown')}",
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
    session.commit()
    return bool(result.get("ok", False))


async def _scale_up(
    session: Session,
    deployment: Deployment,
    application: Application,
    release: Release,
    config: HealerYamlV1,
    agent,
    count: int,
    *,
    server_id: uuid.UUID,
    port_start: int,
    port_end: int,
) -> bool:
    health_check = session.scalars(
        select(HealthCheck).where(HealthCheck.application_id == application.id)
    ).first()
    server = session.get(Server, server_id)

    overall_ok = True
    for _ in range(count):
        try:
            instance = _allocate_instance(
                session,
                application=application,
                release=release,
                server_id=server_id,
                port_start=port_start,
                port_end=port_end,
            )
        except DeploymentSetupError as exc:
            _log(session, deployment, "error", str(exc))
            overall_ok = False
            break  # no more free ports in range — further replicas can't help

        instance.deployment_id = deployment.id
        InstanceRepository(session).transition(instance, InstanceStatus.STARTING)
        session.commit()

        start_payload = _build_start_instance_payload(session, release, instance, config)
        start_command = await command_service.submit_command_and_wait(
            session,
            agent,
            AgentCommandType.START_INSTANCE,
            start_payload,
            idempotency_key=f"start-instance:{instance.id}",
            ttl_seconds=200,
            wait_seconds=180.0,
        )
        start_ok = _persist_instance_command_outcome(
            session, deployment, start_command, port=instance.port
        )
        if not start_ok:
            InstanceRepository(session).transition(instance, InstanceStatus.FAILED)
            session.commit()
            overall_ok = False
            continue

        if health_check is not None and server is not None:
            healthy = await asyncio.to_thread(
                health_check_service.wait_until_healthy,
                session,
                health_check,
                instance.id,
                host=server.hostname,
                port=instance.port,
            )
        else:
            # No health check configured for this application — trust the
            # Agent's own start_instance success.
            healthy = True

        if healthy:
            InstanceRepository(session).transition(instance, InstanceStatus.RUNNING)
            session.commit()
        else:
            _log(
                session,
                deployment,
                "error",
                f"instance on port {instance.port} did not become healthy in time",
            )
            InstanceRepository(session).transition(instance, InstanceStatus.UNHEALTHY)
            session.commit()
            overall_ok = False

    return overall_ok


async def _scale_down(
    session: Session,
    deployment: Deployment,
    application: Application,
    config: HealerYamlV1,
    live_instances: list[Instance],
    count: int,
    *,
    agent,
) -> bool:
    # Remove the most recently created instances first — keeps the
    # oldest/original replicas running.
    to_drain = sorted(live_instances, key=lambda i: i.created_at, reverse=True)[:count]

    for instance in to_drain:
        instance.deployment_id = deployment.id
        InstanceRepository(session).transition(instance, InstanceStatus.DRAINING)
    session.commit()

    # One gateway sync for the whole batch: gateway_service only ever
    # includes RUNNING instances in the upstream, so every instance just
    # marked DRAINING is excluded from the very next reload — this is what
    # actually stops *new* requests from reaching it. Existing requests on
    # already-established connections to it are unaffected by an Nginx
    # reload (see docs/scaling.md) and keep running independently.
    if config.domain is not None:
        await gateway_service.sync_gateway(session, application, actor_id=deployment.created_by)

    await asyncio.sleep(DEFAULT_DRAIN_TIMEOUT_SECONDS)

    overall_ok = True
    for instance in to_drain:
        stop_command = await command_service.submit_command_and_wait(
            session,
            agent,
            AgentCommandType.STOP_INSTANCE,
            _build_stop_instance_payload(instance, config),
            idempotency_key=f"stop-instance:{instance.id}",
            ttl_seconds=60,
            wait_seconds=45.0,
        )
        stop_ok = _persist_instance_command_outcome(
            session, deployment, stop_command, port=instance.port
        )
        InstanceRepository(session).transition(
            instance, InstanceStatus.STOPPED if stop_ok else InstanceStatus.FAILED
        )
        session.commit()
        overall_ok = overall_ok and stop_ok

    return overall_ok


async def run_scale(session: Session, deployment_id: uuid.UUID) -> None:
    """The actual scale pipeline. Runs as a FastAPI BackgroundTask against
    the triggering request's own session — see `start_scale`. Always
    releases the application's operation lock on the way out, whatever the
    outcome.
    """
    deployment = DeploymentRepository(session).get(deployment_id)
    if deployment is None:
        return
    try:
        application = session.get(Application, deployment.application_id)
        release = session.get(Release, deployment.release_id)
        if application is None or release is None:
            return
        if (
            application.server_id is None
            or application.port_range_start is None
            or application.port_range_end is None
        ):
            _log(session, deployment, "error", "application is missing its server or port range")
            transition_deployment(session, deployment, DeploymentStatus.FAILED)
            session.commit()
            return
        server_id = application.server_id
        port_range_start = application.port_range_start
        port_range_end = application.port_range_end

        config = application_service.config_from_application(application)
        agent = AgentRepository(session).get_by_server_id(server_id)
        if agent is None:
            _log(
                session,
                deployment,
                "error",
                "the target server's Agent disappeared before scaling could run",
            )
            transition_deployment(session, deployment, DeploymentStatus.FAILED)
            session.commit()
            return

        target = deployment.instance_count
        live = _live_instances(session, application.id)
        current = len(live)

        if target > current:
            ok = await _scale_up(
                session,
                deployment,
                application,
                release,
                config,
                agent,
                target - current,
                server_id=server_id,
                port_start=port_range_start,
                port_end=port_range_end,
            )
        elif target < current:
            ok = await _scale_down(
                session, deployment, application, config, live, current - target, agent=agent
            )
        else:
            ok = True

        if ok and config.domain is not None:
            # Scale-up's new RUNNING instances still need one sync to
            # actually be added as upstreams (scale-down already synced once
            # to remove drained ones before the wait). A no-op (already
            # correct) sync when target == current is cheap and keeps
            # routing correct even if a prior sync attempt had failed.
            result = await gateway_service.sync_gateway(
                session, application, actor_id=deployment.created_by
            )
            if not result.ok:
                _log(session, deployment, "error", f"gateway sync: {result.message}")

        transition_deployment(
            session, deployment, DeploymentStatus.SUCCEEDED if ok else DeploymentStatus.FAILED
        )
        session.commit()
    finally:
        lock_service.release(session, deployment.application_id)


def list_instances(session: Session, application_id: uuid.UUID) -> list[InstanceView]:
    """Full current-fleet view for the dashboard's instance table — every
    instance regardless of status (not just "live" ones), newest first.
    """
    instances = session.scalars(
        select(Instance).where(Instance.application_id == application_id).order_by(Instance.port)
    ).all()

    views = []
    for instance in instances:
        server = session.get(Server, instance.server_id)
        release = session.get(Release, instance.release_id) if instance.release_id else None
        latest_result = session.scalars(
            select(HealthCheckResult)
            .where(HealthCheckResult.instance_id == instance.id)
            .order_by(HealthCheckResult.checked_at.desc())
        ).first()
        views.append(
            InstanceView(
                id=instance.id,
                port=instance.port,
                server_id=instance.server_id,
                server_name=server.name if server else "unknown",
                status=instance.status.value,
                release_version=release.ref if release else "",
                service_name=instance.service_name,
                healthy=latest_result.healthy if latest_result else None,
                response_time_ms=latest_result.response_time_ms if latest_result else None,
                last_checked_at=latest_result.checked_at if latest_result else None,
                failure_reason=instance.failure_reason,
                healing_attempts=instance.healing_attempts,
                created_at=instance.created_at,
            )
        )
    return views
