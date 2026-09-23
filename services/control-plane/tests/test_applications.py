import threading
import uuid

from tests.support.auth import login_as
from tests.support.csrf import csrf_headers
from tests.support.fake_agent import FakeAgent

WINDOWS_CONFIG = {
    "version": 1,
    "name": "RIT Academic ERP",
    "adapter": "windows-waitress-service",
    "source": {"type": "folder", "location": "C:\\apps\\erp"},
    "windows": {
        "python_executable": "C:\\apps\\erp\\venv\\Scripts\\python.exe",
        "wsgi_module": "erp.wsgi",
        "settings_module": "erp.settings.production",
    },
    "health": {"path": "/health/"},
    "ports": {"start": 9034, "end": 9039},
    "domain": {"hostname": "erp.ritrjpm.edu.in"},
    "secrets": ["DB_PASSWORD"],
}


def _register_server(client, db_session, *, os: str = "windows") -> str:
    """Registering a server needs Administrator — logs in as one (switching
    away from whatever role the test was previously using), creates the
    server, and returns its id. The caller must log in again afterward as
    whatever role it actually wants to test with.
    """
    login_as(
        client, db_session, role="Administrator", email=f"admin-{uuid.uuid4().hex[:6]}@healer.test"
    )
    response = client.post(
        "/servers",
        json={"name": "target", "hostname": f"srv-{uuid.uuid4().hex[:8]}.internal", "os": os},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _config_for(server_id: str, **overrides) -> dict:
    config = {**WINDOWS_CONFIG, "server_id": server_id}
    config.update(overrides)
    return config


# --- create / view / edit ---------------------------------------------------------


def test_viewer_cannot_create_an_application(client, db_session):
    login_as(client, db_session, role="Viewer")
    response = client.post("/applications", json=_config_for(None), headers=csrf_headers(client))
    assert response.status_code == 403


def test_operator_can_create_view_and_update_an_application(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-crud@healer.test")

    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "RIT Academic ERP"
    assert body["adapter_type"] == "windows-waitress-service"
    assert body["config"]["health"]["path"] == "/health/"
    application_id = body["id"]

    view = client.get(f"/applications/{application_id}")
    assert view.status_code == 200
    assert view.json()["slug"] == body["slug"]

    updated = client.patch(
        f"/applications/{application_id}",
        json=_config_for(server_id, name="RIT Academic ERP v2"),
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "RIT Academic ERP v2"
    assert (
        updated.json()["slug"] == body["slug"]
    ), "editing the name should not change an existing slug"


def test_creating_two_applications_gets_distinct_slugs(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-slugs@healer.test")

    first = client.post(
        "/applications",
        json=_config_for(server_id, domain={"hostname": "one.example.test"}),
        headers=csrf_headers(client),
    )
    second = client.post(
        "/applications",
        json=_config_for(server_id, domain={"hostname": "two.example.test"}),
        headers=csrf_headers(client),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["slug"] != second.json()["slug"]


# --- parse-yaml --------------------------------------------------------------------


def test_parse_yaml_endpoint_returns_structured_errors(client, db_session):
    login_as(client, db_session, role="Viewer")
    response = client.post("/applications/parse-yaml", json={"yaml_text": "version: 2\nname: x\n"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["config"] is None
    assert "version" in body["errors"][0]["field"]


def test_parse_yaml_endpoint_accepts_a_valid_config(client, db_session):
    login_as(client, db_session, role="Viewer")
    yaml_text = (
        "version: 1\nname: x\nadapter: linux-docker\n"
        "source:\n  type: image\n  location: myrepo/x:latest\n"
        "linux:\n  internal_port: 8000\n"
        "health:\n  path: /healthz\n"
        "ports:\n  start: 9100\n  end: 9101\n"
    )
    response = client.post("/applications/parse-yaml", json={"yaml_text": yaml_text})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["config"]["adapter"] == "linux-docker"


# --- domain uniqueness -------------------------------------------------------------


def test_reusing_a_hostname_across_applications_is_rejected(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-domain@healer.test")

    first = client.post(
        "/applications",
        json=_config_for(server_id, domain={"hostname": "shared.example.test"}),
        headers=csrf_headers(client),
    )
    assert first.status_code == 201

    second = client.post(
        "/applications",
        json=_config_for(server_id, name="another app", domain={"hostname": "shared.example.test"}),
        headers=csrf_headers(client),
    )
    assert second.status_code == 409


# --- validate: no agent / disconnected agent ---------------------------------------


def test_validate_reports_error_when_server_has_no_agent(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-noagent@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    response = client.post(f"/applications/{application_id}/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert any("no enrolled Agent" in i["message"] for i in body["issues"])


# --- validate: secrets ---------------------------------------------------------------


def test_validate_reports_missing_secret(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-secret1@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    response = client.post(f"/applications/{application_id}/validate")
    body = response.json()
    assert any(i["field"] == "secrets.DB_PASSWORD" for i in body["issues"])


def test_setting_a_secret_clears_the_missing_secret_issue(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-secret2@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    set_response = client.post(
        f"/applications/{application_id}/secrets",
        json={"key": "DB_PASSWORD", "value": "super-secret-value"},
        headers=csrf_headers(client),
    )
    assert set_response.status_code == 204

    listed = client.get(f"/applications/{application_id}/secrets")
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "key": "DB_PASSWORD",
            "created_at": listed.json()[0]["created_at"],
            "updated_at": listed.json()[0]["updated_at"],
        }
    ]
    assert "value" not in listed.text and "super-secret-value" not in listed.text

    response = client.post(f"/applications/{application_id}/validate")
    body = response.json()
    assert not any(i["field"] == "secrets.DB_PASSWORD" for i in body["issues"])


# --- validate: real command round trip through a fake agent ------------------------


def test_validate_runs_the_command_on_a_connected_agent_and_translates_the_result(
    client, db_session
):
    server_id = _register_server(client, db_session)
    token_response = client.post(
        f"/servers/{server_id}/enrollment-tokens", headers=csrf_headers(client)
    )
    raw_token = token_response.json()["token"]

    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    credential = enrolled["credential"]

    login_as(client, db_session, role="Operator", email="operator-validate@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]
    client.post(
        f"/applications/{application_id}/secrets",
        json={"key": "DB_PASSWORD", "value": "x"},
        headers=csrf_headers(client),
    )

    with client.websocket_connect(
        "/ws/agent", headers={"Authorization": f"Bearer {credential}"}
    ) as ws:
        fake = FakeAgent(ws, os="windows", arch="amd64", adapters=["windows-waitress-service"])
        fake.hello()

        result_holder = {}

        def respond():
            command = fake.receive_command()
            result_holder["payload"] = command
            fake.send_event(command["command_id"], "acknowledged")
            fake.send_event(command["command_id"], "running")
            fake.send_event(
                command["command_id"],
                "succeeded",
                result={
                    "checks": [
                        {
                            "name": "windows.python_executable",
                            "severity": "error",
                            "passed": False,
                            "message": "python.exe: file does not exist",
                        },
                        {
                            "name": "health_path",
                            "severity": "info",
                            "passed": True,
                            "message": "well-formed",
                        },
                    ]
                },
            )

        responder = threading.Thread(target=respond)
        responder.start()

        response = client.post(f"/applications/{application_id}/validate")
        responder.join(timeout=5)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    messages = {i["field"]: i["message"] for i in body["issues"]}
    assert "windows.python_executable" in messages
    assert "does not exist" in messages["windows.python_executable"]
    assert result_holder["payload"]["type"] == "validate_app"


def test_viewer_can_run_validate(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="setup-viewer-test@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]
    client.post("/auth/logout", headers=csrf_headers(client))

    login_as(client, db_session, role="Viewer", email="viewer-validate@healer.test")
    response = client.post(f"/applications/{application_id}/validate")
    assert response.status_code == 200
