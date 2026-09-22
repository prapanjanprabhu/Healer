import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.agent import AgentCommand
from app.db.models.application import Instance
from app.db.models.domain import Domain
from app.db.models.enums import AgentCommandStatus, AgentCommandType, InstanceStatus
from tests.factories import make_agent, make_application, make_server


def test_duplicate_port_on_same_server_is_rejected(db_session):
    server = make_server(db_session)
    application = make_application(db_session)
    db_session.add(Instance(application_id=application.id, server_id=server.id, port=9034))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Instance(application_id=application.id, server_id=server.id, port=9034))
            db_session.flush()


def test_same_port_on_different_servers_is_allowed(db_session):
    server_a = make_server(db_session)
    server_b = make_server(db_session)
    application = make_application(db_session)

    db_session.add(Instance(application_id=application.id, server_id=server_a.id, port=9034))
    db_session.add(Instance(application_id=application.id, server_id=server_b.id, port=9034))
    db_session.flush()  # should not raise


def test_duplicate_domain_hostname_is_rejected(db_session):
    application = make_application(db_session)
    db_session.add(Domain(application_id=application.id, hostname="erp.ritrjpm.edu.in"))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Domain(application_id=application.id, hostname="erp.ritrjpm.edu.in"))
            db_session.flush()


def test_duplicate_agent_command_idempotency_key_is_rejected(db_session):
    agent = make_agent(db_session)
    key = str(uuid.uuid4())
    db_session.add(
        AgentCommand(
            agent_id=agent.id,
            command_type=AgentCommandType.INSTANCE_RESTART,
            payload={},
            idempotency_key=key,
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                AgentCommand(
                    agent_id=agent.id,
                    command_type=AgentCommandType.INSTANCE_RESTART,
                    payload={},
                    idempotency_key=key,
                )
            )
            db_session.flush()


def test_instance_status_defaults_to_pending(db_session):
    server = make_server(db_session)
    application = make_application(db_session)
    instance = Instance(application_id=application.id, server_id=server.id, port=9035)
    db_session.add(instance)
    db_session.flush()

    assert instance.status == InstanceStatus.PENDING


def test_agent_command_status_defaults_to_pending(db_session):
    agent = make_agent(db_session)
    command = AgentCommand(
        agent_id=agent.id,
        command_type=AgentCommandType.DEPLOY,
        payload={"release_id": str(uuid.uuid4())},
        idempotency_key=str(uuid.uuid4()),
    )
    db_session.add(command)
    db_session.flush()

    assert command.status == AgentCommandStatus.PENDING
