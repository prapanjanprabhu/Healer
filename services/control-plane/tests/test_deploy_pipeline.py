import threading
import uuid

from tests.support.auth import login_as
from tests.support.csrf import csrf_headers
from tests.support.fake_agent import FakeAgent

from app.db.models.application import Instance
from app.db.models.enums import AgentStatus, InstanceStatus
from app.schemas.healer_yaml import HealerYamlV1
from app.services import application_service, deployment_service
from app.services.deployment_service import DeploymentSetupError
from tests.factories import make_agent, make_server

WINDOWS_CONFIG = {
    "version": 1,
    "name": "RIT Academic ERP",
    "adapter": "windows-waitress-service",
    "source": {"type": "folder", "location": "C:\\HealerTest\\erp"},
    "windows": {
        "python_executable": "C:\\Python\\python.exe",
        "wsgi_module": "erp.wsgi",
        "settings_module": "erp.settings",
    },
    "health": {"path": "/health/"},
    "ports": {"start": 9034, "end": 9039},
    "secrets": [],
}


def _config_for(server_id: str, **overrides) -> dict:
    config = {**WINDOWS_CONFIG, "server_id": server_id}
    config.update(overrides)
    return config


def _register_server(client, db_session, *, os: str = "windows") -> str:
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


# --- start_deployment (service layer, no network) ---------------------------------


def test_start_deployment_rejects_a_disconnected_agent(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.DISCONNECTED)
    config = HealerYamlV1.model_validate(_config_for(str(server.id)))
    application = application_service.create_application(db_session, config)

    try:
        deployment_service.start_deployment(db_session, application, config, actor_id=None)
        assert False, "expected DeploymentSetupError"
    except DeploymentSetupError as exc:
        assert "not currently connected" in str(exc)


def test_start_deployment_allocates_the_next_free_port(db_session):
    server = make_server(db_session)
    make_agent(
        db_session,
        server=server,
        status=AgentStatus.CONNECTED,
        capabilities={"os": "windows", "adapters": ["windows-waitress-service"]},
    )
    config = HealerYamlV1.model_validate(
        _config_for(str(server.id), ports={"start": 9034, "end": 9036})
    )
    application = application_service.create_application(db_session, config)

    # Occupy the first port in the range with another application's instance.
    other_app = application_service.create_application(
        db_session,
        HealerYamlV1.model_validate(
            _config_for(str(server.id), name="Other App", ports={"start": 9034, "end": 9036})
        ),
    )
    db_session.add(
        Instance(
            application_id=other_app.id,
            server_id=server.id,
            port=9034,
            status=InstanceStatus.RUNNING,
            service_name="Healer-other-app-9034",
        )
    )
    db_session.flush()

    deployment = deployment_service.start_deployment(db_session, application, config, actor_id=None)
    instances = (
        db_session.query(Instance).filter(Instance.release_id == deployment.release_id).all()
    )
    assert len(instances) == 1
    assert instances[0].port == 9035, "9034 is taken, so allocation should skip to the next port"
    assert instances[0].service_name == f"Healer-{application.slug}-9035"


def test_start_deployment_fails_when_the_port_range_is_full(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(
        _config_for(str(server.id), ports={"start": 9034, "end": 9034})
    )
    application = application_service.create_application(db_session, config)
    db_session.add(
        Instance(
            application_id=application.id,
            server_id=server.id,
            port=9034,
            status=InstanceStatus.RUNNING,
            service_name="taken",
        )
    )
    db_session.flush()

    try:
        deployment_service.start_deployment(db_session, application, config, actor_id=None)
        assert False, "expected DeploymentSetupError"
    except DeploymentSetupError as exc:
        assert "no free port" in str(exc)


# --- full pipeline, through the real API + a fake Agent over a real WS ------------


def _deploy_release_success_result() -> dict:
    return {
        "ok": True,
        "steps": [
            {"name": "snapshot", "status": "succeeded", "message": "copied 12 files"},
            {"name": "shared_dirs", "status": "succeeded", "message": "linked shared storage"},
            {"name": "venv", "status": "succeeded", "message": "created virtual environment"},
            {"name": "pip_install", "status": "succeeded", "message": "installed requirements"},
            {"name": "django_check", "status": "succeeded", "message": "no issues"},
            {"name": "migrate", "status": "succeeded", "message": "applied 18 migrations"},
            {"name": "collectstatic", "status": "succeeded", "message": "127 files copied"},
        ],
        "release_dir": "C:\\ProgramData\\Healer\\apps\\rit-academic-erp\\releases\\20260923050000",
        "venv_python": (
            "C:\\ProgramData\\Healer\\apps\\rit-academic-erp\\releases\\20260923050000"
            "\\.venv\\Scripts\\python.exe"
        ),
    }


def _start_instance_success_result(service_name: str) -> dict:
    return {
        "ok": True,
        "service_name": service_name,
        "steps": [
            {"name": "permissions", "status": "succeeded", "message": "granted access"},
            {"name": "service_install", "status": "succeeded", "message": "created service"},
            {"name": "service_start", "status": "succeeded", "message": "service is running"},
        ],
    }


def test_deploy_endpoint_runs_the_full_pipeline_to_a_running_instance(client, db_session):
    server_id = _register_server(client, db_session)
    token_response = client.post(
        f"/servers/{server_id}/enrollment-tokens", headers=csrf_headers(client)
    )
    raw_token = token_response.json()["token"]
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    credential = enrolled["credential"]

    login_as(client, db_session, role="Operator", email="operator-deploy@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    with client.websocket_connect(
        "/ws/agent", headers={"Authorization": f"Bearer {credential}"}
    ) as ws:
        fake = FakeAgent(ws, os="windows", arch="amd64", adapters=["windows-waitress-service"])
        fake.hello()

        service_name_holder = {}

        def respond():
            deploy_command = fake.receive_command()
            fake.send_event(deploy_command["command_id"], "acknowledged")
            fake.send_event(deploy_command["command_id"], "running")
            fake.send_event(
                deploy_command["command_id"], "succeeded", result=_deploy_release_success_result()
            )

            start_command = fake.receive_command()
            service_name_holder["name"] = start_command["payload"]["service_name"]
            fake.send_event(start_command["command_id"], "acknowledged")
            fake.send_event(start_command["command_id"], "running")
            fake.send_event(
                start_command["command_id"],
                "succeeded",
                result=_start_instance_success_result(start_command["payload"]["service_name"]),
            )

        responder = threading.Thread(target=respond)
        responder.start()

        deploy_response = client.post(
            f"/applications/{application_id}/deploy", headers=csrf_headers(client)
        )
        responder.join(timeout=10)

    assert deploy_response.status_code == 202, deploy_response.text
    body = deploy_response.json()
    assert 9034 <= body["port"] <= 9039
    assert body["service_name"] == service_name_holder["name"]

    detail = client.get(f"/deployments/{body['deployment_id']}")
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["status"] == "succeeded"
    assert detail_body["instance"]["status"] == "running"
    assert detail_body["instance"]["port"] == body["port"]
    step_names = [s["name"] for s in detail_body["steps"]]
    assert step_names == [
        "snapshot",
        "shared_dirs",
        "venv",
        "pip_install",
        "django_check",
        "migrate",
        "collectstatic",
        "permissions",
        "service_install",
        "service_start",
    ]
    assert all(s["status"] == "succeeded" for s in detail_body["steps"])
    assert len(detail_body["logs"]) == len(detail_body["steps"])


def test_deploy_endpoint_reports_a_failed_step_and_never_starts_the_instance(client, db_session):
    server_id = _register_server(client, db_session)
    token_response = client.post(
        f"/servers/{server_id}/enrollment-tokens", headers=csrf_headers(client)
    )
    raw_token = token_response.json()["token"]
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    credential = enrolled["credential"]

    login_as(client, db_session, role="Operator", email="operator-deploy-fail@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    failing_result = {
        "ok": False,
        "steps": [
            {"name": "snapshot", "status": "succeeded", "message": "copied 12 files"},
            {"name": "shared_dirs", "status": "succeeded", "message": "linked shared storage"},
            {"name": "venv", "status": "succeeded", "message": "created virtual environment"},
            {
                "name": "pip_install",
                "status": "failed",
                "message": "could not find a version that satisfies the requirement Django",
            },
            {"name": "django_check", "status": "skipped", "message": "skipped after an earlier step failed"},
            {"name": "migrate", "status": "skipped", "message": "skipped after an earlier step failed"},
            {
                "name": "collectstatic",
                "status": "skipped",
                "message": "skipped after an earlier step failed",
            },
        ],
    }

    with client.websocket_connect(
        "/ws/agent", headers={"Authorization": f"Bearer {credential}"}
    ) as ws:
        fake = FakeAgent(ws, os="windows", arch="amd64", adapters=["windows-waitress-service"])
        fake.hello()

        def respond():
            deploy_command = fake.receive_command()
            fake.send_event(deploy_command["command_id"], "acknowledged")
            fake.send_event(deploy_command["command_id"], "running")
            fake.send_event(deploy_command["command_id"], "succeeded", result=failing_result)

        responder = threading.Thread(target=respond)
        responder.start()

        deploy_response = client.post(
            f"/applications/{application_id}/deploy", headers=csrf_headers(client)
        )
        responder.join(timeout=10)

    assert deploy_response.status_code == 202, deploy_response.text
    deployment_id = deploy_response.json()["deployment_id"]

    detail = client.get(f"/deployments/{deployment_id}").json()
    assert detail["status"] == "failed"
    assert detail["instance"]["status"] == "failed"
    by_name = {s["name"]: s["status"] for s in detail["steps"]}
    assert by_name["pip_install"] == "failed"
    assert by_name["django_check"] == "skipped"
    assert "service_install" not in by_name, "start_instance must never run after deploy_release fails"


def test_viewer_cannot_trigger_a_deploy(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Viewer")
    create_response = client.post(
        "/applications", json=_config_for(server_id), headers=csrf_headers(client)
    )
    # Viewer can't even create the application (needs "deploy"); use a
    # throwaway Operator login just to set up the fixture, then switch back.
    if create_response.status_code == 403:
        login_as(client, db_session, role="Operator", email="operator-setup@healer.test")
        create_response = client.post(
            "/applications", json=_config_for(server_id), headers=csrf_headers(client)
        )
        login_as(client, db_session, role="Viewer", email="viewer-deploy@healer.test")

    application_id = create_response.json()["id"]
    response = client.post(
        f"/applications/{application_id}/deploy", headers=csrf_headers(client)
    )
    assert response.status_code == 403


def test_deploy_returns_409_when_no_agent_is_connected(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-no-agent@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    response = client.post(f"/applications/{application_id}/deploy", headers=csrf_headers(client))
    assert response.status_code == 409
    assert "not currently connected" in response.json()["detail"]
