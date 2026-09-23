"""Blue-green release deploys and rollback — see docs/blue-green-deployment.md.

Reuses the Deployment/DeploymentStep/DeploymentLog tables (`kind`
`"blue_green"` or `"rollback"`). Unlike a plain scale-up (Phase 9), a
blue-green switch is all-or-nothing: every one of the new release's
instances must pass its health gate before *any* traffic moves — a single
failure aborts the whole switch, stops whatever new instances it started,
and leaves the currently active release exactly as it was. Nginx activation
is atomic too: the Gateway Manager's own `nginx -t`/restore-on-failure
(Phase 8) means a bad config for the new release can never replace the
working one, and this module additionally reverts `active_release_id` if
that happens so the database matches what's actually being routed.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.application import Application, Instance, Release, Source
from app.db.models.deployment import Deployment
from app.db.models.enums import (
    AgentCommandType,
    AgentStatus,
    DeploymentStatus,
    InstanceStatus,
    ReleaseStatus,
)
from app.db.models.health import HealthCheck
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
    _build_deploy_release_payload,
    _build_start_instance_payload,
    _persist_agent_outcome,
    transition_deployment,
)
from app.services.scale_service import _log, _persist_instance_command_outcome

MIGRATION_WARNING = (
    "This deploy runs migrations against the shared database while the previous "
    "release may still be briefly serving traffic. Follow expand/migrate/contract: "
    "this release should only ADD nullable columns, new tables, or backward-compatible "
    "changes — never remove or rename anything the previous release's code still reads. "
    "Remove old schema only in a LATER release, once no running instance depends on it. "
    "See docs/blue-green-deployment.md."
)

# The new release's instances are never routed to until every one of them is
# healthy, so a batch that gets aborted mid-way was never serving traffic —
# no drain wait is needed to stop them. The *old* release's instances, which
# genuinely were serving until the switch, get this same grace period
# Phase 9's scale-down uses.
DEFAULT_DRAIN_TIMEOUT_SECONDS = 15


class ReleaseSetupError(Exception):
    """A problem that prevents even starting a blue-green deploy/rollback —
    surfaced as a 4xx, never turned into a Deployment row that immediately
    fails.
    """


def _require_agent(session: Session, application: Application):
    if application.active_release_id is None:
        raise ReleaseSetupError(
            "application has no active release yet — deploy it first with "
            "POST /applications/{id}/deploy"
        )
    if (
        application.server_id is None
        or application.port_range_start is None
        or application.port_range_end is None
    ):
        raise ReleaseSetupError("application has no target server or port range configured")
    agent = AgentRepository(session).get_by_server_id(application.server_id)
    if agent is None or agent.status != AgentStatus.CONNECTED:
        raise ReleaseSetupError("the target server's Agent is not currently connected")
    return agent


def start_new_release(
    session: Session, application: Application, config: HealerYamlV1, *, actor_id: uuid.UUID | None
) -> Deployment:
    """Builds and health-gates a brand-new release, then atomically switches
    Nginx to it and drains the previous one. Caller must hold the
    application's operation lock (acquired by the route before calling).
    """
    _require_agent(session, application)
    source = session.scalars(select(Source).where(Source.application_id == application.id)).first()
    if source is None:
        raise ReleaseSetupError("application has no source configured")

    release_version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    release = Release(
        application_id=application.id,
        source_id=source.id,
        ref=release_version,
        status=ReleaseStatus.PENDING,
    )
    session.add(release)
    session.flush()

    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.PENDING,
        instance_count=application.desired_replicas,
        kind="blue_green",
        created_by=actor_id,
    )
    session.add(deployment)
    session.flush()
    transition_deployment(session, deployment, DeploymentStatus.IN_PROGRESS, actor_id=actor_id)
    session.commit()
    return deployment


def start_rollback(
    session: Session,
    application: Application,
    target_release_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None,
) -> Deployment:
    """Re-runs the same health-gated switch against a previously-successful
    release's already-built code (no deploy_release rebuild needed).
    """
    _require_agent(session, application)
    target = session.get(Release, target_release_id)
    if target is None or target.application_id != application.id:
        raise ReleaseSetupError("release not found for this application")
    if target.id == application.active_release_id:
        raise ReleaseSetupError("that release is already active")
    if target.status != ReleaseStatus.READY or not target.release_dir or not target.venv_python:
        raise ReleaseSetupError(
            "release is not available to roll back to "
            "(never finished building, or has since been pruned)"
        )

    deployment = Deployment(
        application_id=application.id,
        release_id=target.id,
        status=DeploymentStatus.PENDING,
        instance_count=application.desired_replicas,
        kind="rollback",
        created_by=actor_id,
    )
    session.add(deployment)
    session.flush()
    transition_deployment(session, deployment, DeploymentStatus.IN_PROGRESS, actor_id=actor_id)
    session.commit()
    return deployment


async def _build_release(
    session: Session,
    deployment: Deployment,
    application: Application,
    release: Release,
    config,
    agent,
) -> bool:
    release.status = ReleaseStatus.BUILDING
    session.commit()
    payload = _build_deploy_release_payload(application, release, config)
    command = await command_service.submit_command_and_wait(
        session,
        agent,
        AgentCommandType.DEPLOY_RELEASE,
        payload,
        idempotency_key=f"deploy-release:{deployment.id}",
        ttl_seconds=600,
        wait_seconds=480.0,
    )
    ok = _persist_agent_outcome(session, deployment, command)
    if ok:
        result = command.result or {}
        release.release_dir = result.get("release_dir")
        release.venv_python = result.get("venv_python")
        release.status = ReleaseStatus.READY
    else:
        release.status = ReleaseStatus.FAILED
    session.commit()
    return ok


async def _stop_instances(
    session: Session, deployment: Deployment, agent, instances: list[Instance]
) -> None:
    for instance in instances:
        stop_command = await command_service.submit_command_and_wait(
            session,
            agent,
            AgentCommandType.STOP_INSTANCE,
            {"service_name": instance.service_name},
            idempotency_key=f"abort-stop-instance:{instance.id}",
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


async def _start_and_health_gate(
    session: Session,
    deployment: Deployment,
    application: Application,
    release: Release,
    config,
    agent,
    *,
    server_id: uuid.UUID,
    port_start: int,
    port_end: int,
) -> list[Instance] | None:
    """Starts and health-verifies every new instance the switch needs.
    Returns None (having already stopped anything it started) the moment a
    single one fails — an all-or-nothing gate, never a partial cutover.
    """
    health_check = session.scalars(
        select(HealthCheck).where(HealthCheck.application_id == application.id)
    ).first()
    server = session.get(Server, server_id)
    started: list[Instance] = []

    for _ in range(deployment.instance_count):
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
            await _stop_instances(session, deployment, agent, started)
            return None

        instance.deployment_id = deployment.id
        InstanceRepository(session).transition(instance, InstanceStatus.STARTING)
        session.commit()

        start_payload = _build_start_instance_payload(release, instance, config)
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
            await _stop_instances(session, deployment, agent, started)
            return None

        healthy = True
        if health_check is not None and server is not None:
            healthy = await asyncio.to_thread(
                health_check_service.wait_until_healthy,
                session,
                health_check,
                instance.id,
                host=server.hostname,
                port=instance.port,
            )
        if not healthy:
            _log(
                session,
                deployment,
                "error",
                f"instance on port {instance.port} did not become healthy in time",
            )
            InstanceRepository(session).transition(instance, InstanceStatus.FAILED)
            session.commit()
            await _stop_instances(session, deployment, agent, started)
            return None

        InstanceRepository(session).transition(instance, InstanceStatus.RUNNING)
        session.commit()
        started.append(instance)

    return started


async def _drain_old_release(
    session: Session,
    deployment: Deployment,
    application: Application,
    agent,
    old_release_id: uuid.UUID,
) -> None:
    old_instances = session.scalars(
        select(Instance).where(
            Instance.release_id == old_release_id, Instance.status == InstanceStatus.RUNNING
        )
    ).all()
    if not old_instances:
        return

    for instance in old_instances:
        InstanceRepository(session).transition(instance, InstanceStatus.DRAINING)
    session.commit()

    # The gateway already reflects only the new release by the time this is
    # called, so these are already excluded from the upstream — this wait
    # just lets requests already in flight on existing connections finish.
    await asyncio.sleep(DEFAULT_DRAIN_TIMEOUT_SECONDS)

    for instance in old_instances:
        stop_command = await command_service.submit_command_and_wait(
            session,
            agent,
            AgentCommandType.STOP_INSTANCE,
            {"service_name": instance.service_name},
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


def _prune_old_releases(session: Session, application: Application) -> None:
    keep = max(application.release_retention_count, 1)
    releases = session.scalars(
        select(Release)
        .where(Release.application_id == application.id, Release.status == ReleaseStatus.READY)
        .order_by(Release.created_at.desc())
    ).all()
    for release in releases[keep:]:
        if release.id == application.active_release_id:
            continue  # defensive — should never happen, the active one is always the newest
        session.delete(release)
    session.commit()


async def _fail(
    session: Session,
    deployment: Deployment,
    reason: str,
    *,
    agent=None,
    cleanup_release: Release | None = None,
    cleanup_instances: list[Instance] | None = None,
) -> None:
    if cleanup_instances and agent is not None:
        await _stop_instances(session, deployment, agent, cleanup_instances)
    if cleanup_release is not None and cleanup_release.status != ReleaseStatus.READY:
        cleanup_release.status = ReleaseStatus.FAILED
    deployment.failure_reason = reason
    _log(session, deployment, "error", reason)
    transition_deployment(session, deployment, DeploymentStatus.FAILED)
    session.commit()


async def run_release_switch(session: Session, deployment_id: uuid.UUID) -> None:
    """The blue-green/rollback pipeline. Runs as a FastAPI BackgroundTask —
    see `start_new_release`/`start_rollback`. Always releases the
    application's operation lock on the way out, whatever the outcome.
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
            await _fail(session, deployment, "application is missing its server or port range")
            return
        server_id = application.server_id
        port_range_start = application.port_range_start
        port_range_end = application.port_range_end

        config = application_service.config_from_application(application)
        agent = AgentRepository(session).get_by_server_id(server_id)
        if agent is None:
            await _fail(
                session,
                deployment,
                "the target server's Agent disappeared before the switch could run",
            )
            return

        if deployment.kind == "blue_green":
            if not await _build_release(session, deployment, application, release, config, agent):
                await _fail(session, deployment, "release build failed", cleanup_release=release)
                return

        new_instances = await _start_and_health_gate(
            session,
            deployment,
            application,
            release,
            config,
            agent,
            server_id=server_id,
            port_start=port_range_start,
            port_end=port_range_end,
        )
        if new_instances is None:
            await _fail(
                session,
                deployment,
                "one or more new instances failed to start or become healthy",
                cleanup_release=release,
            )
            return

        old_release_id = application.active_release_id
        application.active_release_id = release.id
        session.commit()

        if config.domain is not None:
            result = await gateway_service.sync_gateway(
                session, application, actor_id=deployment.created_by
            )
            if not result.ok:
                # The Gateway Manager already restored the previous working
                # Nginx config on its own (Phase 8) — keep the database in
                # sync with what's actually being routed.
                application.active_release_id = old_release_id
                session.commit()
                await _fail(
                    session,
                    deployment,
                    f"gateway rejected the new release, traffic was not switched: {result.message}",
                    agent=agent,
                    cleanup_release=release,
                    cleanup_instances=new_instances,
                )
                return

        if old_release_id is not None:
            await _drain_old_release(session, deployment, application, agent, old_release_id)

        _prune_old_releases(session, application)
        transition_deployment(session, deployment, DeploymentStatus.SUCCEEDED)
        session.commit()
    finally:
        lock_service.release(session, deployment.application_id)
