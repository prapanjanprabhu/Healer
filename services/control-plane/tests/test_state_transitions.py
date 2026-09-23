import uuid

import pytest

from app.db.models.agent import AgentCommand
from app.db.models.application import Instance
from app.db.models.audit import AuditLog
from app.db.models.deployment import Deployment
from app.db.models.enums import (
    AgentCommandStatus,
    AgentCommandType,
    DeploymentStatus,
    InstanceStatus,
)
from app.domain.state_machines import InvalidTransition
from app.repositories.agent_command_repository import AgentCommandRepository
from app.repositories.deployment_repository import DeploymentRepository
from app.repositories.instance_repository import InstanceRepository
from app.services.deployment_service import transition_deployment
from tests.factories import make_agent, make_application, make_release, make_server


def test_deployment_happy_path(db_session):
    application = make_application(db_session)
    release = make_release(db_session, application=application)
    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.PENDING,
        instance_count=2,
    )
    db_session.add(deployment)
    db_session.flush()

    repo = DeploymentRepository(db_session)
    repo.transition(deployment, DeploymentStatus.IN_PROGRESS)
    repo.transition(deployment, DeploymentStatus.SUCCEEDED)
    assert deployment.status == DeploymentStatus.SUCCEEDED

    repo.transition(deployment, DeploymentStatus.ROLLED_BACK)
    assert deployment.status == DeploymentStatus.ROLLED_BACK


def test_deployment_cannot_skip_in_progress(db_session):
    application = make_application(db_session)
    release = make_release(db_session, application=application)
    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.PENDING,
        instance_count=1,
    )
    db_session.add(deployment)
    db_session.flush()

    repo = DeploymentRepository(db_session)
    with pytest.raises(InvalidTransition):
        repo.transition(deployment, DeploymentStatus.SUCCEEDED)


def test_deployment_rolled_back_is_terminal(db_session):
    application = make_application(db_session)
    release = make_release(db_session, application=application)
    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.ROLLED_BACK,
        instance_count=1,
    )
    db_session.add(deployment)
    db_session.flush()

    repo = DeploymentRepository(db_session)
    with pytest.raises(InvalidTransition):
        repo.transition(deployment, DeploymentStatus.IN_PROGRESS)


def test_transition_deployment_service_writes_audit_log(db_session):
    application = make_application(db_session)
    release = make_release(db_session, application=application)
    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.PENDING,
        instance_count=1,
    )
    db_session.add(deployment)
    db_session.flush()

    transition_deployment(db_session, deployment, DeploymentStatus.IN_PROGRESS)
    assert deployment.status == DeploymentStatus.IN_PROGRESS

    log = db_session.query(AuditLog).filter(AuditLog.target_id == str(deployment.id)).one()
    assert log.action == "deployment.transition"
    assert log.detail == {"from": "pending", "to": "in_progress"}


def test_instance_health_driven_removal_and_restart(db_session):
    server = make_server(db_session)
    application = make_application(db_session)
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        port=9036,
        status=InstanceStatus.RUNNING,
    )
    db_session.add(instance)
    db_session.flush()

    repo = InstanceRepository(db_session)
    repo.transition(instance, InstanceStatus.UNHEALTHY)
    repo.transition(instance, InstanceStatus.STOPPED)
    repo.transition(instance, InstanceStatus.STARTING)
    repo.transition(instance, InstanceStatus.RUNNING)
    assert instance.status == InstanceStatus.RUNNING


def test_instance_restarting_transitions(db_session):
    server = make_server(db_session)
    application = make_application(db_session)
    instance = Instance(
        application_id=application.id,
        server_id=server.id,
        port=9038,
        status=InstanceStatus.RUNNING,
    )
    db_session.add(instance)
    db_session.flush()

    repo = InstanceRepository(db_session)
    repo.transition(instance, InstanceStatus.UNHEALTHY)
    repo.transition(instance, InstanceStatus.RESTARTING)
    repo.transition(instance, InstanceStatus.RUNNING)
    assert instance.status == InstanceStatus.RUNNING

    repo.transition(instance, InstanceStatus.UNHEALTHY)
    repo.transition(instance, InstanceStatus.RESTARTING)
    repo.transition(instance, InstanceStatus.FAILED)
    assert instance.status == InstanceStatus.FAILED

    with pytest.raises(InvalidTransition):
        repo.transition(instance, InstanceStatus.RESTARTING)


def test_instance_cannot_go_directly_from_pending_to_running(db_session):
    server = make_server(db_session)
    application = make_application(db_session)
    instance = Instance(application_id=application.id, server_id=server.id, port=9037)
    db_session.add(instance)
    db_session.flush()
    assert instance.status == InstanceStatus.PENDING

    repo = InstanceRepository(db_session)
    with pytest.raises(InvalidTransition):
        repo.transition(instance, InstanceStatus.RUNNING)


def test_agent_command_succeeded_is_terminal(db_session):
    agent = make_agent(db_session)
    command = AgentCommand(
        agent_id=agent.id,
        command_type=AgentCommandType.RESTART_INSTANCE,
        payload={},
        idempotency_key=str(uuid.uuid4()),
    )
    db_session.add(command)
    db_session.flush()

    repo = AgentCommandRepository(db_session)
    repo.transition(command, AgentCommandStatus.SENT)
    repo.transition(command, AgentCommandStatus.ACKNOWLEDGED)
    repo.transition(command, AgentCommandStatus.RUNNING)
    repo.transition(command, AgentCommandStatus.SUCCEEDED)

    with pytest.raises(InvalidTransition):
        repo.transition(command, AgentCommandStatus.FAILED)


def test_agent_command_idempotency_lookup(db_session):
    agent = make_agent(db_session)
    key = str(uuid.uuid4())
    command = AgentCommand(
        agent_id=agent.id,
        command_type=AgentCommandType.DEPLOY_RELEASE,
        payload={},
        idempotency_key=key,
    )
    db_session.add(command)
    db_session.flush()

    repo = AgentCommandRepository(db_session)
    found = repo.get_by_idempotency_key(key)
    assert found is not None
    assert found.id == command.id
    assert repo.get_by_idempotency_key("does-not-exist") is None
