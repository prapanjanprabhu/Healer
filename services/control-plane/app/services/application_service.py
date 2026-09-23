"""Creates/updates the Application row and its related Source/Domain/
HealthCheck rows from a parsed healer.yaml. Never touches Instance,
Release, migrations, or anything that would start a process or reconfigure
Nginx — see docs/app-validation.md.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.application import Application, Source
from app.db.models.domain import Domain
from app.db.models.enums import AdapterType, HealthCheckType, SourceType
from app.db.models.health import HealthCheck
from app.schemas.healer_yaml import HealerYamlV1


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "app"


def _unique_slug(session: Session, base: str) -> str:
    slug = base
    suffix = 2
    while session.scalars(select(Application).where(Application.slug == slug)).first() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def create_application(session: Session, config: HealerYamlV1) -> Application:
    application = Application(
        name=config.name,
        slug=_unique_slug(session, _slugify(config.name)),
        adapter_type=AdapterType(config.adapter),
        server_id=config.server_id,
        config=config.model_dump(mode="json"),
        port_range_start=config.ports.start,
        port_range_end=config.ports.end,
        min_replicas=config.replicas.min,
        max_replicas=config.replicas.max,
        desired_replicas=config.replicas.min,
    )
    session.add(application)
    session.flush()
    _sync_related_rows(session, application, config)
    return application


def update_application(
    session: Session, application: Application, config: HealerYamlV1
) -> Application:
    # slug is deliberately stable across renames — later phases reference it
    # in things that are expensive or unsafe to rename in place (a Windows
    # Service name, an Nginx upstream name). Renaming the *display* name
    # should never silently move those.
    application.name = config.name
    application.adapter_type = AdapterType(config.adapter)
    application.server_id = config.server_id
    application.config = config.model_dump(mode="json")
    application.port_range_start = config.ports.start
    application.port_range_end = config.ports.end
    application.min_replicas = config.replicas.min
    application.max_replicas = config.replicas.max
    # Keep the live scaling target inside the (possibly just-narrowed) bounds
    # rather than resetting it — editing config should never itself trigger
    # a scale operation.
    application.desired_replicas = min(
        max(application.desired_replicas, config.replicas.min), config.replicas.max
    )
    session.flush()
    _sync_related_rows(session, application, config)
    return application


def _sync_related_rows(session: Session, application: Application, config: HealerYamlV1) -> None:
    source = session.scalars(select(Source).where(Source.application_id == application.id)).first()
    if source is None:
        source = Source(application_id=application.id)
        session.add(source)
    source.source_type = SourceType(config.source.type)
    source.location = config.source.location
    source.ref = config.source.ref

    health_check = session.scalars(
        select(HealthCheck).where(HealthCheck.application_id == application.id)
    ).first()
    if health_check is None:
        health_check = HealthCheck(application_id=application.id, check_type=HealthCheckType.HTTP)
        session.add(health_check)
    health_check.path = config.health.path
    health_check.interval_seconds = config.health.interval_seconds
    health_check.timeout_seconds = config.health.timeout_seconds
    health_check.healthy_threshold = config.health.healthy_threshold
    health_check.unhealthy_threshold = config.health.unhealthy_threshold

    if config.domain is not None:
        domain = session.scalars(
            select(Domain).where(Domain.application_id == application.id)
        ).first()
        if domain is None:
            domain = Domain(application_id=application.id)
            session.add(domain)
        domain.hostname = config.domain.hostname
        domain.cert_path = config.domain.cert_path
        domain.key_path = config.domain.key_path

    session.flush()


def config_from_application(application: Application) -> HealerYamlV1:
    """Reload the stored config back into the typed schema — used to
    re-validate an existing application without the caller resending the
    whole descriptor.
    """
    return HealerYamlV1.model_validate(application.config)
