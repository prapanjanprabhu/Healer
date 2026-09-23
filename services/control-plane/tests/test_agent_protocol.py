import uuid
from datetime import UTC, datetime, timedelta

from app.core.security import hash_token
from app.db.models.server import EnrollmentToken
from tests.factories import DEFAULT_TEST_PASSWORD, make_server
from tests.support.auth import login_as as _login_as
from tests.support.csrf import csrf_headers
from tests.support.fake_agent import FakeAgent

PASSWORD = DEFAULT_TEST_PASSWORD


def _register_server_and_token(client, db_session) -> tuple[str, str]:
    """Logs in as Administrator, registers a server, issues an enrollment
    token. Returns (server_id, raw_enrollment_token).
    """
    _login_as(client, db_session, role="Administrator", email="admin-registrar@healer.test")
    create = client.post(
        "/servers",
        json={"name": "erp-01", "hostname": f"erp-{uuid.uuid4().hex[:8]}.internal", "os": "linux"},
        headers=csrf_headers(client),
    )
    assert create.status_code == 201, create.text
    server_id = create.json()["id"]

    token_response = client.post(
        f"/servers/{server_id}/enrollment-tokens", headers=csrf_headers(client)
    )
    assert token_response.status_code == 201, token_response.text
    raw_token = token_response.json()["token"]

    client.post("/auth/logout", headers=csrf_headers(client))
    return server_id, raw_token


# --- server registration -------------------------------------------------------


def test_viewer_cannot_register_a_server(client, db_session):
    _login_as(client, db_session, role="Viewer")
    response = client.post(
        "/servers",
        json={"name": "x", "hostname": f"x-{uuid.uuid4().hex}.internal", "os": "linux"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403


def test_duplicate_hostname_is_rejected(client, db_session):
    _login_as(client, db_session, role="Administrator")
    hostname = f"dup-{uuid.uuid4().hex[:8]}.internal"
    first = client.post(
        "/servers",
        json={"name": "a", "hostname": hostname, "os": "linux"},
        headers=csrf_headers(client),
    )
    assert first.status_code == 201
    second = client.post(
        "/servers",
        json={"name": "b", "hostname": hostname, "os": "linux"},
        headers=csrf_headers(client),
    )
    assert second.status_code == 409


# --- enrollment tokens -----------------------------------------------------------


def test_enrollment_token_is_single_use(client, db_session):
    server_id, raw_token = _register_server_and_token(client, db_session)

    first = client.post("/agents/enroll", json={"token": raw_token})
    assert first.status_code == 200, first.text

    second = client.post("/agents/enroll", json={"token": raw_token})
    assert second.status_code == 401


def test_expired_enrollment_token_is_rejected(client, db_session):
    server = make_server(db_session)
    raw_token = "expired-token-value"
    db_session.add(
        EnrollmentToken(
            server_id=server.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    db_session.flush()

    response = client.post("/agents/enroll", json={"token": raw_token})
    assert response.status_code == 401


def test_revoked_enrollment_token_is_rejected(client, db_session):
    _login_as(client, db_session, role="Administrator", email="revoker@healer.test")
    create = client.post(
        "/servers",
        json={
            "name": "erp-02",
            "hostname": f"erp2-{uuid.uuid4().hex[:8]}.internal",
            "os": "windows",
        },
        headers=csrf_headers(client),
    )
    server_id = create.json()["id"]
    issued = client.post(f"/servers/{server_id}/enrollment-tokens", headers=csrf_headers(client))
    token_id = issued.json()["id"]
    raw_token = issued.json()["token"]

    revoke = client.delete(
        f"/servers/{server_id}/enrollment-tokens/{token_id}", headers=csrf_headers(client)
    )
    assert revoke.status_code == 204

    response = client.post("/agents/enroll", json={"token": raw_token})
    assert response.status_code == 401


def test_unknown_token_is_rejected(client):
    response = client.post("/agents/enroll", json={"token": "not-a-real-token"})
    assert response.status_code == 401


# --- connection lifecycle: online / offline / reconnect --------------------------


def test_agent_appears_online_while_connected_and_offline_after_disconnect(client, db_session):
    server_id, raw_token = _register_server_and_token(client, db_session)
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    credential = enrolled["credential"]

    _login_as(client, db_session, role="Viewer", email="watcher@healer.test")
    before_connect = client.get(f"/servers/{server_id}").json()
    assert before_connect["online"] is False

    with client.websocket_connect(
        "/ws/agent", headers={"Authorization": f"Bearer {credential}"}
    ) as ws:
        agent = FakeAgent(ws)
        agent.hello()
        agent.heartbeat()

        while_connected = client.get(f"/servers/{server_id}").json()
        assert while_connected["online"] is True
        assert while_connected["agent_version"] == "0.1.0-test"

    after_disconnect = client.get(f"/servers/{server_id}").json()
    assert after_disconnect["online"] is False


def test_ws_connect_rejects_invalid_credential(client, db_session):
    _register_server_and_token(client, db_session)  # unused token/credential
    try:
        with client.websocket_connect(
            "/ws/agent", headers={"Authorization": "Bearer not-a-real-credential"}
        ):
            raise AssertionError("connection should have been rejected")
    except Exception:
        pass  # Starlette raises when the server closes during the handshake


# --- commands: safe test command, idempotency, permissions -----------------------


def test_simulated_agent_enrolls_connects_and_completes_a_safe_command(client, db_session):
    """The Phase 4 completion test: enroll once, appear online, receive a
    safe test command (inspect_host), return its result.
    """
    server_id, raw_token = _register_server_and_token(client, db_session)
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    agent_id = enrolled["agent_id"]
    credential = enrolled["credential"]

    with client.websocket_connect(
        "/ws/agent", headers={"Authorization": f"Bearer {credential}"}
    ) as ws:
        fake = FakeAgent(ws)
        fake.hello()

        _login_as(client, db_session, role="Operator", email="operator-cmd@healer.test")
        server_status = client.get(f"/servers/{server_id}").json()
        assert server_status["online"] is True

        submit = client.post(
            f"/agents/{agent_id}/commands",
            json={"type": "inspect_host", "payload": {}},
            headers=csrf_headers(client),
        )
        assert submit.status_code == 201, submit.text
        command_id = submit.json()["id"]
        assert submit.json()["status"] == "sent"

        received = fake.run_command_to_success(result={"cpu_count": 4, "os": "linux"})
        assert received["type"] == "inspect_host"
        assert received["command_id"] == command_id

    final = client.get(f"/agents/{agent_id}/commands/{command_id}")
    assert final.status_code == 200
    body = final.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"cpu_count": 4, "os": "linux"}


def test_duplicate_command_submission_is_idempotent(client, db_session):
    server_id, raw_token = _register_server_and_token(client, db_session)
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    agent_id = enrolled["agent_id"]
    credential = enrolled["credential"]

    _login_as(client, db_session, role="Operator", email="dup-cmd@healer.test")
    idempotency_key = str(uuid.uuid4())

    with client.websocket_connect(
        "/ws/agent", headers={"Authorization": f"Bearer {credential}"}
    ) as ws:
        FakeAgent(ws).hello()

        first = client.post(
            f"/agents/{agent_id}/commands",
            json={"type": "inspect_host", "payload": {}, "idempotency_key": idempotency_key},
            headers=csrf_headers(client),
        )
        second = client.post(
            f"/agents/{agent_id}/commands",
            json={"type": "inspect_host", "payload": {}, "idempotency_key": idempotency_key},
            headers=csrf_headers(client),
        )
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

    commands = client.get(f"/agents/{agent_id}/commands").json()
    matching = [c for c in commands if c["id"] == first.json()["id"]]
    assert len(matching) == 1


def test_viewer_cannot_submit_a_scale_command(client, db_session):
    server_id, raw_token = _register_server_and_token(client, db_session)
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    agent_id = enrolled["agent_id"]

    _login_as(client, db_session, role="Viewer", email="viewer-cmd@healer.test")
    response = client.post(
        f"/agents/{agent_id}/commands",
        json={"type": "start_instance", "payload": {}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403


def test_viewer_can_submit_a_view_command(client, db_session):
    server_id, raw_token = _register_server_and_token(client, db_session)
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    agent_id = enrolled["agent_id"]

    _login_as(client, db_session, role="Viewer", email="viewer-cmd2@healer.test")
    response = client.post(
        f"/agents/{agent_id}/commands",
        json={"type": "inspect_host", "payload": {}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201


# --- reconnect delivers commands queued while offline -----------------------------


def test_command_submitted_while_offline_is_delivered_on_reconnect(client, db_session):
    server_id, raw_token = _register_server_and_token(client, db_session)
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    agent_id = enrolled["agent_id"]
    credential = enrolled["credential"]

    _login_as(client, db_session, role="Operator", email="reconnect-cmd@healer.test")
    submit = client.post(
        f"/agents/{agent_id}/commands",
        json={"type": "inspect_host", "payload": {}},
        headers=csrf_headers(client),
    )
    assert submit.status_code == 201
    assert submit.json()["status"] == "pending"  # agent wasn't connected yet
    command_id = submit.json()["id"]

    with client.websocket_connect(
        "/ws/agent", headers={"Authorization": f"Bearer {credential}"}
    ) as ws:
        fake = FakeAgent(ws)
        received = fake.run_command_to_success()
        assert received["command_id"] == command_id

    final = client.get(f"/agents/{agent_id}/commands/{command_id}")
    assert final.json()["status"] == "succeeded"


# --- timeout / expiry ------------------------------------------------------------


def test_overdue_pending_command_expires_on_next_list_call(client, db_session):
    from app.db.models.agent import Agent, AgentCommand
    from app.db.models.enums import AgentCommandStatus, AgentCommandType

    server = make_server(db_session)
    agent = Agent(
        server_id=server.id,
        agent_version="0.1.0-test",
        credential_hash="unused-in-this-test",
    )
    db_session.add(agent)
    db_session.flush()

    command = AgentCommand(
        agent_id=agent.id,
        command_type=AgentCommandType.INSPECT_HOST,
        payload={},
        idempotency_key=str(uuid.uuid4()),
        status=AgentCommandStatus.PENDING,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db_session.add(command)
    db_session.flush()

    _login_as(client, db_session, role="Viewer", email="expiry-watcher@healer.test")
    listed = client.get(f"/agents/{agent.id}/commands").json()
    matching = next(c for c in listed if c["id"] == str(command.id))
    assert matching["status"] == "expired"
