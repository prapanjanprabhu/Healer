"""Orchestrates every check `POST /applications/{id}/validate` runs.

Nothing here deploys anything, runs a migration, starts a process, or
touches Nginx — see docs/app-validation.md for the exact boundary. Windows/
Linux filesystem, interpreter, Docker, and port checks happen *on the
managed server*, via the existing `validate_app` structured command (never
a shell command) sent to that server's Agent.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.application import Application, Instance
from app.db.models.domain import Domain
from app.db.models.enums import AgentCommandType, AgentStatus
from app.db.models.secret import SecretRecord
from app.repositories.agent_repository import AgentRepository
from app.schemas.healer_yaml import HealerYamlV1
from app.services import command_service

Severity = Literal["error", "warning", "info"]


@dataclass
class ValidationIssue:
    field: str
    severity: Severity
    message: str


def _issue(field: str, severity: Severity, message: str) -> ValidationIssue:
    return ValidationIssue(field=field, severity=severity, message=message)


async def validate_application(
    session: Session, application: Application, config: HealerYamlV1
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues += _validate_domain_uniqueness(session, application, config)
    issues += _validate_secrets(session, application, config)
    issues += _validate_port_range_bookkeeping(session, application, config)
    issues += await _validate_certificate_pair(config)
    issues += await _validate_on_agent(session, application, config)
    return issues


def _validate_domain_uniqueness(
    session: Session, application: Application, config: HealerYamlV1
) -> list[ValidationIssue]:
    if config.domain is None:
        return []
    stmt = select(Domain).where(Domain.hostname == config.domain.hostname)
    existing = session.scalars(stmt).first()
    if existing is not None and existing.application_id != application.id:
        return [
            _issue(
                "domain.hostname",
                "error",
                f"hostname {config.domain.hostname!r} is already used by another application",
            )
        ]
    return []


def _validate_secrets(
    session: Session, application: Application, config: HealerYamlV1
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for name in config.secrets:
        stmt = select(SecretRecord).where(
            SecretRecord.key == name,
            (SecretRecord.application_id == application.id)
            | (SecretRecord.application_id.is_(None)),
        )
        if session.scalars(stmt).first() is None:
            # Deliberately never echoes a value — there is none to echo;
            # existence is all this checks.
            issues.append(_issue(f"secrets.{name}", "error", f"secret {name!r} has not been set"))
    return issues


def _validate_port_range_bookkeeping(
    session: Session, application: Application, config: HealerYamlV1
) -> list[ValidationIssue]:
    if config.server_id is None:
        return []
    stmt = select(Instance).where(
        Instance.server_id == config.server_id,
        Instance.application_id != application.id,
        Instance.port >= config.ports.start,
        Instance.port <= config.ports.end,
    )
    conflicting = session.scalars(stmt).all()
    if conflicting:
        ports = sorted({i.port for i in conflicting})
        return [
            _issue(
                "ports",
                "warning",
                f"port(s) {ports} in this range are already assigned to another application "
                "on this server (per Healer's own records)",
            )
        ]
    return []


async def _validate_certificate_pair(config: HealerYamlV1) -> list[ValidationIssue]:
    if config.domain is None or not config.domain.cert_path or not config.domain.key_path:
        return []

    url = f"{settings.gateway_manager_internal_url}/certificates/validate"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={"cert_path": config.domain.cert_path, "key_path": config.domain.key_path},
                headers={"X-Gateway-Secret": settings.gateway_manager_shared_secret},
            )
    except httpx.HTTPError as exc:
        return [
            _issue(
                "domain.cert_path",
                "warning",
                f"could not reach the Gateway Manager to verify the certificate pair: {exc}",
            )
        ]

    body = response.json()
    if response.status_code != 200:
        return [
            _issue("domain.cert_path", "error", body.get("detail", "certificate validation failed"))
        ]

    issues: list[ValidationIssue] = []
    for check in body.get("checks", []):
        if not check["passed"]:
            issues.append(_issue(f"domain.{check['name']}", check["severity"], check["message"]))
    return issues


async def _validate_on_agent(
    session: Session, application: Application, config: HealerYamlV1
) -> list[ValidationIssue]:
    if config.server_id is None:
        return [_issue("server_id", "error", "no target server selected")]

    agent = AgentRepository(session).get_by_server_id(config.server_id)
    if agent is None:
        return [_issue("server_id", "error", "the target server has no enrolled Agent yet")]

    capabilities = agent.capabilities or {}
    adapters = capabilities.get("adapters") or []
    if adapters and config.adapter not in adapters:
        return [
            _issue(
                "adapter",
                "error",
                f"the target server's Agent does not support adapter {config.adapter!r} "
                f"(it reports: {adapters})",
            )
        ]

    if agent.status != AgentStatus.CONNECTED:
        return [
            _issue(
                "server_id",
                "error",
                "the target server's Agent is not currently connected — cannot run "
                "filesystem/interpreter/Docker/port checks on it right now",
            )
        ]

    payload = _build_validate_app_payload(config)
    idempotency_key = f"validate-app:{application.id}:{uuid.uuid4()}"
    command = await command_service.submit_command_and_wait(
        session,
        agent,
        AgentCommandType.VALIDATE_APP,
        payload,
        idempotency_key,
        ttl_seconds=30,
        wait_seconds=20.0,
    )

    if command.status.value not in ("succeeded", "failed"):
        return [
            _issue(
                "server_id",
                "warning",
                f"the Agent did not return a validation result in time (command status: "
                f"{command.status.value}) — try again",
            )
        ]

    if command.error:
        return [_issue("server_id", "error", f"Agent validation failed: {command.error}")]

    issues: list[ValidationIssue] = []
    for check in (command.result or {}).get("checks", []):
        if not check.get("passed", False):
            issues.append(
                _issue(
                    check.get("name", "agent"),
                    check.get("severity", "error"),
                    check.get("message", ""),
                )
            )
    return issues


def _build_validate_app_payload(config: HealerYamlV1) -> dict:
    payload: dict = {
        "adapter": config.adapter,
        "source": {"type": config.source.type, "location": config.source.location},
        "health_path": config.health.path,
        "port_range_start": config.ports.start,
        "port_range_end": config.ports.end,
    }
    if config.windows is not None:
        payload["windows"] = config.windows.model_dump()
    if config.linux is not None:
        payload["linux"] = config.linux.model_dump()
    return payload
