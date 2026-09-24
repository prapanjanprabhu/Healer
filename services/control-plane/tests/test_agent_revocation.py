"""Phase 15: revoking an already-enrolled Agent — previously the only
revocation mechanism was for a pre-enrollment EnrollmentToken, with no way
to cut off a server that had already finished enrollment.
"""

import asyncio

from app.db.models.enums import AgentStatus
from app.services import agent_service, server_service
from tests.factories import make_server
from tests.support.auth import login_as
from tests.support.csrf import csrf_headers


def test_revoke_agent_clears_the_credential_and_marks_disconnected(db_session):
    server = make_server(db_session)
    agent, raw_credential = agent_service.enroll_agent(
        db_session, _issue_enrollment_token_raw(db_session, server)
    )
    db_session.commit()

    asyncio.run(server_service.revoke_agent(db_session, agent))

    db_session.refresh(agent)
    assert agent.credential_hash is None
    assert agent.status == AgentStatus.DISCONNECTED


def test_the_old_credential_no_longer_authenticates_after_revocation(db_session):
    server = make_server(db_session)
    agent, raw_credential = agent_service.enroll_agent(
        db_session, _issue_enrollment_token_raw(db_session, server)
    )
    db_session.commit()
    assert agent_service.authenticate_agent_credential(db_session, raw_credential) is not None

    asyncio.run(server_service.revoke_agent(db_session, agent))

    assert agent_service.authenticate_agent_credential(db_session, raw_credential) is None


def test_revoke_agent_route_requires_manage_servers_permission(client, db_session):
    login_as(client, db_session, role="Operator", email="revoke-op@healer.test")
    server = make_server(db_session)

    response = client.post(f"/servers/{server.id}/agent/revoke", headers=csrf_headers(client))
    assert response.status_code == 403


def test_revoke_agent_route_404s_when_no_agent_is_enrolled(client, db_session):
    login_as(client, db_session, role="Administrator", email="revoke-admin-1@healer.test")
    server = make_server(db_session)

    response = client.post(f"/servers/{server.id}/agent/revoke", headers=csrf_headers(client))
    assert response.status_code == 404


def _issue_enrollment_token_raw(session, server) -> str:
    raw_token, _ = server_service.issue_enrollment_token(session, server)
    session.commit()
    return raw_token
