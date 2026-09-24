"""Bounded, redacted log retrieval — see docs/metrics-and-logs.md.

Two read shapes, both backed by the same Agent command
(AgentCommandType.COLLECT_LOGS -> Go's HandleCollectLogs):

- fetch_instance_log: one bounded request/response, for the dashboard's
  initial view of a log.
- stream_instance_log: an async generator that polls the same command every
  few seconds and yields only newly-appended lines, for the live tail
  (exposed to the dashboard as an SSE endpoint). It manages its own
  short-lived DB sessions since it outlives any single request's session.

Deployment logs are a separate, already-existing source (DeploymentLog rows
via GET /deployments/{id}) — list_log_sources just points at them rather
than re-implementing that read path.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.application import Instance, Release
from app.db.models.enums import AgentCommandType, AgentStatus
from app.db.session import SessionLocal
from app.repositories.agent_repository import AgentRepository
from app.services import command_service, log_redaction, secret_service
from app.services.deployment_service import _shared_log_dir

DEFAULT_MAX_BYTES = 64 * 1024
HARD_MAX_BYTES = 1024 * 1024
DEFAULT_MAX_LINES = 500
HARD_MAX_LINES = 5000

STREAM_POLL_SECONDS = 2.0
STREAM_MAX_SECONDS = 600.0
STREAM_INITIAL_MAX_BYTES = 32 * 1024
STREAM_INITIAL_MAX_LINES = 100
STREAM_POLL_MAX_BYTES = 64 * 1024
STREAM_POLL_MAX_LINES = 500


class LogUnavailableError(Exception):
    """A log can't be fetched right now (agent offline, no release dir yet,
    the agent timed out) — surfaced as a 409/503 by the route, not a 500.
    """


@dataclass
class LogSourceOut:
    id: str
    type: str  # "stdout" | "stderr" | "deployment"
    label: str
    instance_id: uuid.UUID | None


def list_log_sources(session: Session, application_id: uuid.UUID) -> list[LogSourceOut]:
    instances = session.scalars(
        select(Instance)
        .where(Instance.application_id == application_id, Instance.service_name.is_not(None))
        .order_by(Instance.created_at.desc())
    ).all()
    sources: list[LogSourceOut] = []
    for instance in instances:
        label = f"{instance.service_name} (port {instance.port})"
        sources.append(
            LogSourceOut(
                id=f"{instance.id}:stdout",
                type="stdout",
                label=f"{label} — stdout",
                instance_id=instance.id,
            )
        )
        sources.append(
            LogSourceOut(
                id=f"{instance.id}:stderr",
                type="stderr",
                label=f"{label} — stderr",
                instance_id=instance.id,
            )
        )
    sources.append(
        LogSourceOut(
            id="deployment",
            type="deployment",
            label="Deployment logs (all releases)",
            instance_id=None,
        )
    )
    return sources


def _clamp(value: int | None, default: int, hard_cap: int) -> int:
    if value is None or value <= 0 or value > hard_cap:
        return default
    return value


async def _collect(
    session: Session,
    instance: Instance,
    stream: str,
    *,
    max_bytes: int,
    max_lines: int,
    offset: int | None,
) -> dict:
    if instance.release_id is None:
        raise LogUnavailableError("this instance has no known release yet")
    release = session.get(Release, instance.release_id)
    if release is None or not release.release_dir:
        raise LogUnavailableError("this instance's release directory is not known yet")
    if not instance.service_name:
        raise LogUnavailableError("this instance has no service name")

    agent = AgentRepository(session).get_by_server_id(instance.server_id)
    if agent is None or agent.status != AgentStatus.CONNECTED:
        raise LogUnavailableError("the instance's Agent is not currently connected")

    payload = {
        "service_name": instance.service_name,
        "log_dir": _shared_log_dir(release.release_dir),
        "stream": stream,
        "max_bytes": max_bytes,
        "max_lines": max_lines,
        "offset": offset,
    }
    command = await command_service.submit_command_and_wait(
        session,
        agent,
        AgentCommandType.COLLECT_LOGS,
        payload,
        idempotency_key=f"collect-logs:{instance.id}:{stream}:{offset}:{uuid.uuid4()}",
        ttl_seconds=60,
        wait_seconds=15.0,
    )
    if command.status.value != "succeeded":
        raise LogUnavailableError(command.error or "the agent did not return a log result in time")

    result = command.result or {}
    return {
        "lines": result.get("lines", []),
        "size": result.get("size", 0),
        "end_offset": result.get("end_offset", 0),
        "truncated": result.get("truncated", False),
        "not_found": result.get("not_found", False),
    }


async def fetch_instance_log(
    session: Session,
    instance: Instance,
    stream: str,
    *,
    max_bytes: int | None = None,
    max_lines: int | None = None,
    offset: int | None = None,
) -> dict:
    chunk = await _collect(
        session,
        instance,
        stream,
        max_bytes=_clamp(max_bytes, DEFAULT_MAX_BYTES, HARD_MAX_BYTES),
        max_lines=_clamp(max_lines, DEFAULT_MAX_LINES, HARD_MAX_LINES),
        offset=offset,
    )
    secrets = secret_service.get_secret_values(session, instance.application_id)
    chunk["lines"] = log_redaction.redact_lines(chunk["lines"], secrets)
    return chunk


async def stream_instance_log(application_id: uuid.UUID, instance_id: uuid.UUID, stream: str):
    """Yields dicts: {"lines": [...]} for new content, or {"error": "..."} /
    {"closed": "..."} to end the stream. The route formats each as one SSE
    `data:` event. A fresh SessionLocal is opened per poll — this generator
    runs far longer than any single request-scoped session should be held
    open for.
    """
    started = time.monotonic()
    offset: int | None = None
    first = True

    while time.monotonic() - started < STREAM_MAX_SECONDS:
        db = SessionLocal()
        try:
            instance = db.get(Instance, instance_id)
            if instance is None or instance.application_id != application_id:
                yield {"error": "instance not found"}
                return
            try:
                chunk = await _collect(
                    db,
                    instance,
                    stream,
                    max_bytes=STREAM_INITIAL_MAX_BYTES if first else STREAM_POLL_MAX_BYTES,
                    max_lines=STREAM_INITIAL_MAX_LINES if first else STREAM_POLL_MAX_LINES,
                    offset=None if first else offset,
                )
            except LogUnavailableError as exc:
                yield {"error": str(exc)}
                await asyncio.sleep(STREAM_POLL_SECONDS)
                continue
            secrets = secret_service.get_secret_values(db, instance.application_id)
        finally:
            db.close()

        first = False
        offset = chunk["end_offset"]
        if chunk["lines"]:
            yield {"lines": log_redaction.redact_lines(chunk["lines"], secrets)}
        await asyncio.sleep(STREAM_POLL_SECONDS)

    yield {"closed": "stream duration limit reached; reconnect to keep tailing"}
