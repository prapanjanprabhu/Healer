"""Bounded self-healing — see docs/self-healing.md.

Triggered by app/services/health_monitor.py once a RUNNING instance crosses
its configured `unhealthy_threshold`. Caller must already hold the
application's "heal" operation lock (same lock deploy/scale use, so healing
can never race a deploy/scale operation on the same application).

Flow: remove from Nginx (transitioning to UNHEALTHY already excludes it,
since gateway_service only ever includes RUNNING instances in the upstream)
→ attempt a controlled restart (re-issuing start_instance for the same
service_name/port; its own idempotent stop-then-start handling on the Agent
*is* the restart) → verify health → RUNNING and re-added to Nginx on
success. On any failure, this instance is retired for good (FAILED) and a
replacement instance is created on a new port to restore capacity — bounded
by `HealthCheck.max_restart_attempts` across the whole failing "lineage"
(the original instance plus however many replacements it took), never an
unbounded loop. Reaching the limit creates an administrator Notification
and stops trying.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.application import Application, Instance, Release
from app.db.models.enums import AgentCommandType, AgentStatus, InstanceStatus
from app.db.models.health import HealthCheck
from app.db.models.notification import Notification
from app.db.models.server import Server
from app.repositories.agent_repository import AgentRepository
from app.repositories.instance_repository import InstanceRepository
from app.services import (
    application_service,
    audit_service,
    command_service,
    gateway_service,
    health_check_service,
)
from app.services.deployment_service import (
    DeploymentSetupError,
    _allocate_instance,
    _build_start_instance_payload,
)


def _log_audit(session: Session, action: str, instance: Instance, detail: dict) -> None:
    audit_service.record(
        session,
        actor_id=None,
        action=action,
        target_type="instance",
        target_id=str(instance.id),
        detail={"port": instance.port, "application_id": str(instance.application_id), **detail},
    )
    session.commit()


def _notify_administrators(
    session: Session, application: Application, instance: Instance, reason: str
) -> None:
    session.add(
        Notification(
            user_id=None,  # unscoped: every Administrator sees it — see notification.py
            notification_type="self_healing_gave_up",
            message=(
                f"{application.name}: instance on port {instance.port} could not be recovered "
                f"after {instance.healing_attempts} attempt(s) — {reason}"
            ),
        )
    )
    session.commit()


def _give_up(session: Session, application: Application, instance: Instance, reason: str) -> None:
    instance.failure_reason = reason
    if instance.status != InstanceStatus.FAILED:
        InstanceRepository(session).transition(instance, InstanceStatus.FAILED)
    session.commit()
    _log_audit(session, "instance.recovery_failed", instance, {"reason": reason})
    _notify_administrators(session, application, instance, reason)


async def handle_unhealthy_instance(
    session: Session, application: Application, instance: Instance, health_check: HealthCheck
) -> None:
    config = application_service.config_from_application(application)
    server = session.get(Server, instance.server_id)
    agent = AgentRepository(session).get_by_server_id(instance.server_id)
    if agent is not None and agent.status != AgentStatus.CONNECTED:
        agent = None

    # 1. Remove from Nginx before doing anything else. UNHEALTHY is already
    #    excluded from the upstream by gateway_service's RUNNING-only
    #    filter, so transitioning the status *is* the removal.
    if instance.status == InstanceStatus.RUNNING:
        InstanceRepository(session).transition(instance, InstanceStatus.UNHEALTHY)
        session.commit()
    _log_audit(session, "instance.removed_unhealthy", instance, {})
    if config.domain is not None:
        await gateway_service.sync_gateway(session, application)

    if agent is None:
        _give_up(session, application, instance, "the target server's Agent is not connected")
        return

    # Cooldown: don't hammer a flapping instance every monitor tick.
    if instance.last_healing_attempt_at is not None:
        elapsed = (datetime.now(UTC) - instance.last_healing_attempt_at).total_seconds()
        if elapsed < health_check.restart_cooldown_seconds:
            return  # try again once the cooldown has passed

    if instance.healing_attempts >= health_check.max_restart_attempts:
        _give_up(session, application, instance, "maximum restart attempts reached")
        return

    instance.healing_attempts += 1
    instance.last_healing_attempt_at = datetime.now(UTC)
    session.commit()

    release = session.get(Release, instance.release_id) if instance.release_id else None
    if release is None:
        _give_up(session, application, instance, "instance has no associated release to restart")
        return

    InstanceRepository(session).transition(instance, InstanceStatus.RESTARTING)
    session.commit()
    _log_audit(
        session, "instance.restart_attempted", instance, {"attempt": instance.healing_attempts}
    )

    restarted = await _restart(session, agent, release, instance, config)
    healthy = False
    if restarted and server is not None:
        healthy = await asyncio.to_thread(
            health_check_service.wait_until_healthy,
            session,
            health_check,
            instance.id,
            host=server.hostname,
            port=instance.port,
        )

    if healthy:
        InstanceRepository(session).transition(instance, InstanceStatus.RUNNING)
        instance.failure_reason = None
        session.commit()
        _log_audit(session, "instance.recovered", instance, {"attempt": instance.healing_attempts})
        if config.domain is not None:
            await gateway_service.sync_gateway(session, application)
        return

    instance.failure_reason = "restart did not restore a healthy instance"
    InstanceRepository(session).transition(instance, InstanceStatus.FAILED)
    session.commit()
    _log_audit(session, "instance.restart_failed", instance, {"attempt": instance.healing_attempts})

    await _replace(session, application, release, instance, health_check, config, agent, server)


async def _restart(session: Session, agent, release: Release, instance: Instance, config) -> bool:
    """Re-issues start_instance for the same service_name/port — the
    Agent's own idempotent handling (stop and remove any existing service
    under that name before creating a fresh one) *is* the restart.
    """
    payload = _build_start_instance_payload(session, release, instance, config)
    command = await command_service.submit_command_and_wait(
        session,
        agent,
        AgentCommandType.START_INSTANCE,
        payload,
        idempotency_key=f"restart-instance:{instance.id}:{instance.healing_attempts}",
        ttl_seconds=200,
        wait_seconds=180.0,
    )
    if command.status.value not in ("succeeded", "failed"):
        return False
    if command.error:
        return False
    return bool((command.result or {}).get("ok", False))


async def _replace(
    session: Session,
    application: Application,
    release: Release,
    failed_instance: Instance,
    health_check: HealthCheck,
    config,
    agent,
    server: Server | None,
) -> None:
    """Creates a new instance on a new port to restore the capacity the
    failed one held, carrying its healing_attempts count forward so the
    whole lineage stays bounded by max_restart_attempts.
    """
    if application.port_range_start is None or application.port_range_end is None:
        _give_up(session, application, failed_instance, "application has no port range configured")
        return

    try:
        replacement = _allocate_instance(
            session,
            application=application,
            release=release,
            server_id=failed_instance.server_id,
            port_start=application.port_range_start,
            port_end=application.port_range_end,
        )
    except DeploymentSetupError as exc:
        _give_up(
            session, application, failed_instance, f"could not allocate a replacement port: {exc}"
        )
        return

    replacement.healing_attempts = failed_instance.healing_attempts
    replacement.deployment_id = failed_instance.deployment_id
    InstanceRepository(session).transition(replacement, InstanceStatus.STARTING)
    session.commit()
    _log_audit(
        session,
        "instance.replaced",
        failed_instance,
        {"replacement_instance_id": str(replacement.id), "replacement_port": replacement.port},
    )

    start_payload = _build_start_instance_payload(session, release, replacement, config)
    command = await command_service.submit_command_and_wait(
        session,
        agent,
        AgentCommandType.START_INSTANCE,
        start_payload,
        idempotency_key=f"start-instance:{replacement.id}",
        ttl_seconds=200,
        wait_seconds=180.0,
    )
    start_ok = (
        command.status.value in ("succeeded", "failed")
        and not command.error
        and bool((command.result or {}).get("ok", False))
    )
    if not start_ok:
        InstanceRepository(session).transition(replacement, InstanceStatus.FAILED)
        session.commit()
        _give_up(session, application, replacement, "replacement instance failed to start")
        return

    healthy = True
    if server is not None:
        healthy = await asyncio.to_thread(
            health_check_service.wait_until_healthy,
            session,
            health_check,
            replacement.id,
            host=server.hostname,
            port=replacement.port,
        )

    if not healthy:
        InstanceRepository(session).transition(replacement, InstanceStatus.UNHEALTHY)
        session.commit()
        _give_up(session, application, replacement, "replacement instance never became healthy")
        return

    InstanceRepository(session).transition(replacement, InstanceStatus.RUNNING)
    session.commit()
    _log_audit(session, "instance.recovered", replacement, {"via": "replacement"})
    if config.domain is not None:
        await gateway_service.sync_gateway(session, application)
