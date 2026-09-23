"""Synchronizes one application's Nginx routing with the restricted Gateway
Manager after a deploy, or on demand — see docs/gateway-routing.md.

The Gateway Manager has no database access by design (see
docs/security-boundaries.md), so the Control Plane gathers everything needed
to render one application's Nginx server block — its configured domain(s)
and its currently RUNNING instances — and sends that as a single structured
payload over the restricted, shared-secret-authenticated internal call. It
never sends Nginx config text or a shell command, only structured JSON.
"""

import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.application import Application, Instance
from app.db.models.domain import Domain
from app.db.models.enums import InstanceStatus
from app.db.models.server import Server
from app.services import audit_service


@dataclass
class GatewaySyncResult:
    ok: bool
    message: str


def _build_reload_payload(session: Session, application: Application) -> dict:
    domains = session.scalars(select(Domain).where(Domain.application_id == application.id)).all()
    conditions = [
        Instance.application_id == application.id,
        Instance.status == InstanceStatus.RUNNING,
    ]
    # Once an application has gone through a blue-green switch (Phase 11),
    # route only to its active release's instances — a plain "every RUNNING
    # instance" would briefly include *both* releases mid-switch, and an
    # atomic cutover needs exactly one release in the upstream at a time.
    # Apps that predate active_release_id (or have never blue-green
    # deployed) keep the original Phase 8/9 behavior.
    if application.active_release_id is not None:
        conditions.append(Instance.release_id == application.active_release_id)
    instances = session.scalars(select(Instance).where(*conditions)).all()

    upstreams = []
    for instance in instances:
        server = session.get(Server, instance.server_id)
        if server is None:
            continue
        upstreams.append({"host": server.hostname, "port": instance.port})

    return {
        "app_slug": application.slug,
        "domains": [
            {"hostname": d.hostname, "cert_path": d.cert_path, "key_path": d.key_path}
            for d in domains
            if d.cert_path and d.key_path
        ],
        "upstreams": upstreams,
    }


async def sync_gateway(
    session: Session,
    application: Application,
    *,
    actor_id: uuid.UUID | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> GatewaySyncResult:
    """Best-effort: never raises, and never flips a Deployment's own status —
    the deployed instance itself is what determines deploy success/failure,
    a routing problem is a separate, always-visible concern. Every attempt is
    recorded as an audit log entry so a routing failure is never silent even
    though it can't block a deploy.

    `transport` exists only so tests can inject an `httpx.MockTransport`
    instead of a real Gateway Manager connection.
    """
    payload = _build_reload_payload(session, application)
    url = f"{settings.gateway_manager_internal_url}/reload"
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"X-Gateway-Secret": settings.gateway_manager_shared_secret},
            )
    except httpx.HTTPError as exc:
        result = GatewaySyncResult(ok=False, message=f"could not reach the Gateway Manager: {exc}")
    else:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200:
            result = GatewaySyncResult(ok=bool(body.get("ok")), message=body.get("message", ""))
        else:
            result = GatewaySyncResult(
                ok=False,
                message=body.get("detail") or f"gateway manager returned {response.status_code}",
            )

    audit_service.record(
        session,
        actor_id=actor_id,
        action="gateway.sync",
        target_type="application",
        target_id=str(application.id),
        detail={"app_slug": application.slug, "ok": result.ok, "message": result.message},
    )
    session.commit()
    return result
