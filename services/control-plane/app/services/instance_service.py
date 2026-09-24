"""Manual, single-instance restart/stop actions (Phase 14) — the dashboard's
per-instance troubleshooting controls. Distinct from scale_service (which
changes replica COUNT) and self_healing_service (triggered automatically by
failed health checks): these are administrator-invoked, act on exactly one
already-identified instance, and run synchronously — the caller gets a
finished result, not a pollable Deployment, since a single instance's
restart/stop is fast enough not to need a background task.

Both actions hold the application's operation lock for their duration so
they can never race a deploy/scale/release switch.
"""

import uuid

from sqlalchemy.orm import Session

from app.db.models.application import Application, Instance, Release
from app.db.models.enums import AgentCommandType, AgentStatus, InstanceStatus
from app.repositories.agent_repository import AgentRepository
from app.repositories.instance_repository import InstanceRepository
from app.services import application_service, command_service, gateway_service, lock_service
from app.services.deployment_service import (
    _build_start_instance_payload,
    _build_stop_instance_payload,
)
from app.services.lock_service import OperationLockHeldError

_ACTIONABLE_STATUSES = (InstanceStatus.RUNNING, InstanceStatus.UNHEALTHY)


class InstanceActionError(Exception):
    """A restart/stop request that can't be honored — surfaced as a 4xx."""


async def restart_instance(
    session: Session, application: Application, instance: Instance
) -> Instance:
    if instance.status not in _ACTIONABLE_STATUSES:
        raise InstanceActionError(
            f"instance is {instance.status.value}, not in a state that can be restarted"
        )
    agent = AgentRepository(session).get_by_server_id(instance.server_id)
    if agent is None or agent.status != AgentStatus.CONNECTED:
        raise InstanceActionError("the instance's Agent is not currently connected")
    release = session.get(Release, instance.release_id) if instance.release_id else None
    if release is None:
        raise InstanceActionError("this instance has no known release to restart")

    try:
        lock_service.acquire(session, application.id, "restart")
    except OperationLockHeldError as exc:
        raise InstanceActionError(str(exc)) from exc

    try:
        config = application_service.config_from_application(application)

        InstanceRepository(session).transition(instance, InstanceStatus.RESTARTING)
        session.commit()
        if config.domain is not None:
            await gateway_service.sync_gateway(session, application)

        payload = _build_start_instance_payload(session, release, instance, config)
        command = await command_service.submit_command_and_wait(
            session,
            agent,
            AgentCommandType.START_INSTANCE,
            payload,
            idempotency_key=f"manual-restart:{instance.id}:{uuid.uuid4()}",
            ttl_seconds=200,
            wait_seconds=180.0,
        )
        ok = (
            command.status.value == "succeeded"
            and not command.error
            and bool((command.result or {}).get("ok", False))
        )
        if ok:
            instance.failure_reason = None
            InstanceRepository(session).transition(instance, InstanceStatus.RUNNING)
            session.commit()
            if config.domain is not None:
                await gateway_service.sync_gateway(session, application)
            return instance

        instance.failure_reason = command.error or "manual restart failed"
        InstanceRepository(session).transition(instance, InstanceStatus.FAILED)
        session.commit()
        raise InstanceActionError(instance.failure_reason)
    finally:
        lock_service.release(session, application.id)


async def stop_instance(session: Session, application: Application, instance: Instance) -> Instance:
    if instance.status not in _ACTIONABLE_STATUSES:
        raise InstanceActionError(
            f"instance is {instance.status.value}, not in a state that can be stopped"
        )
    agent = AgentRepository(session).get_by_server_id(instance.server_id)
    if agent is None or agent.status != AgentStatus.CONNECTED:
        raise InstanceActionError("the instance's Agent is not currently connected")

    try:
        lock_service.acquire(session, application.id, "stop")
    except OperationLockHeldError as exc:
        raise InstanceActionError(str(exc)) from exc

    try:
        config = application_service.config_from_application(application)

        InstanceRepository(session).transition(instance, InstanceStatus.DRAINING)
        session.commit()
        if config.domain is not None:
            await gateway_service.sync_gateway(session, application)

        payload = _build_stop_instance_payload(instance, config)
        command = await command_service.submit_command_and_wait(
            session,
            agent,
            AgentCommandType.STOP_INSTANCE,
            payload,
            idempotency_key=f"manual-stop:{instance.id}:{uuid.uuid4()}",
            ttl_seconds=60,
            wait_seconds=45.0,
        )
        ok = command.status.value == "succeeded" and not command.error
        InstanceRepository(session).transition(
            instance, InstanceStatus.STOPPED if ok else InstanceStatus.FAILED
        )
        if not ok:
            instance.failure_reason = command.error or "manual stop failed"
        session.commit()
        if not ok:
            raise InstanceActionError(instance.failure_reason)
        return instance
    finally:
        lock_service.release(session, application.id)
