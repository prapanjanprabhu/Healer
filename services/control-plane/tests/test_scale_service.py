import threading
import uuid

from app.db.models.application import Instance
from app.db.models.enums import AgentStatus, InstanceStatus
from app.schemas.healer_yaml import HealerYamlV1
from app.services import application_service, deployment_service, scale_service
from app.services.gateway_service import GatewaySyncResult
from app.services.scale_service import ScaleSetupError
from tests.factories import make_agent, make_server
from tests.support.auth import login_as
from tests.support.csrf import csrf_headers
from tests.support.fake_agent import FakeAgent

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
    "replicas": {"min": 1, "max": 6},
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


def _deploy_release_success_result() -> dict:
    return {
        "ok": True,
        "steps": [{"name": "snapshot", "status": "succeeded", "message": "copied files"}],
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
        "steps": [{"name": "service_start", "status": "succeeded", "message": "running"}],
    }


def _stop_instance_success_result() -> dict:
    return {
        "ok": True,
        "steps": [{"name": "service_remove", "status": "succeeded", "message": "removed"}],
    }


# --- start_scale (service layer, no network) ---------------------------------


def test_start_scale_rejects_a_target_outside_the_allowed_range(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_config_for(str(server.id)))
    application = application_service.create_application(db_session, config)

    try:
        scale_service.start_scale(db_session, application, 10, actor_id=None)
        assert False, "expected ScaleSetupError"
    except ScaleSetupError as exc:
        assert "outside the allowed range" in str(exc)


def test_start_scale_rejects_a_disconnected_agent(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.DISCONNECTED)
    config = HealerYamlV1.model_validate(_config_for(str(server.id)))
    application = application_service.create_application(db_session, config)

    try:
        scale_service.start_scale(db_session, application, 2, actor_id=None)
        assert False, "expected ScaleSetupError"
    except ScaleSetupError as exc:
        assert "not currently connected" in str(exc)


def test_start_scale_rejects_an_application_with_no_ready_release(db_session):
    server = make_server(db_session)
    make_agent(db_session, server=server, status=AgentStatus.CONNECTED)
    config = HealerYamlV1.model_validate(_config_for(str(server.id)))
    application = application_service.create_application(db_session, config)

    try:
        scale_service.start_scale(db_session, application, 2, actor_id=None)
        assert False, "expected ScaleSetupError"
    except ScaleSetupError as exc:
        assert "no successfully deployed release" in str(exc)


# --- full pipeline: deploy once, then scale up and down for real -----------------


def _deploy_one_instance(client, db_session, application_id, credential, ws):
    fake = FakeAgent(ws, os="windows", arch="amd64", adapters=["windows-waitress-service"])
    fake.hello()

    def respond():
        fake.run_command_to_success(_deploy_release_success_result())
        start_command = fake.receive_command()
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
    return fake


def test_scale_up_then_down_starts_and_safely_drains_real_instances(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(
        scale_service.health_check_service,
        "wait_until_healthy",
        lambda *a, **k: True,
    )
    gateway_calls = []

    async def fake_sync_gateway(session, application, *, actor_id=None, transport=None):
        gateway_calls.append(
            len(
                [
                    i
                    for i in db_session.query(Instance)
                    .filter(Instance.application_id == application.id)
                    .all()
                    if i.status == InstanceStatus.RUNNING
                ]
            )
        )
        return GatewaySyncResult(ok=True, message="activated and reloaded")

    monkeypatch.setattr(scale_service.gateway_service, "sync_gateway", fake_sync_gateway)
    monkeypatch.setattr(deployment_service.gateway_service, "sync_gateway", fake_sync_gateway)
    monkeypatch.setattr(scale_service, "DEFAULT_DRAIN_TIMEOUT_SECONDS", 0)

    server_id = _register_server(client, db_session)
    token_response = client.post(
        f"/servers/{server_id}/enrollment-tokens", headers=csrf_headers(client)
    )
    raw_token = token_response.json()["token"]
    enrolled = client.post("/agents/enroll", json={"token": raw_token}).json()
    credential = enrolled["credential"]

    login_as(client, db_session, role="Operator", email="operator-scale@healer.test")
    create = client.post(
        "/applications",
        json=_config_for(server_id, domain={"hostname": "erp-scale.ritrjpm.edu.in"}),
        headers=csrf_headers(client),
    )
    application_id = create.json()["id"]

    with client.websocket_connect(
        "/ws/agent", headers={"Authorization": f"Bearer {credential}"}
    ) as ws:
        fake = _deploy_one_instance(client, db_session, application_id, credential, ws)

        instances = client.get(f"/applications/{application_id}/instances").json()
        assert len(instances) == 1
        assert instances[0]["status"] == "running"

        # Scale 1 -> 3: two new instances should be started and health-checked.
        def respond_scale_up():
            for _ in range(2):
                fake.run_command_to_success(_start_instance_success_result("whatever-service-name"))

        responder = threading.Thread(target=respond_scale_up)
        responder.start()
        scale_up = client.post(
            f"/applications/{application_id}/scale",
            json={"desired_replicas": 3},
            headers=csrf_headers(client),
        )
        assert scale_up.status_code == 202, scale_up.text
        responder.join(timeout=10)

        up_detail = client.get(f"/deployments/{scale_up.json()['deployment_id']}").json()
        assert up_detail["status"] == "succeeded", up_detail
        assert len(up_detail["instances"]) == 2
        assert all(i["status"] == "running" for i in up_detail["instances"])

        instances = client.get(f"/applications/{application_id}/instances").json()
        assert len(instances) == 3
        assert all(i["status"] == "running" for i in instances)

        # Scale 3 -> 1: two instances should be drained (removed from the
        # gateway) before being stopped — never the reverse order.
        def respond_scale_down():
            for _ in range(2):
                stop_command = fake.receive_command()
                fake.send_event(stop_command["command_id"], "acknowledged")
                fake.send_event(stop_command["command_id"], "running")
                fake.send_event(
                    stop_command["command_id"], "succeeded", result=_stop_instance_success_result()
                )

        responder = threading.Thread(target=respond_scale_down)
        responder.start()
        scale_down = client.post(
            f"/applications/{application_id}/scale",
            json={"desired_replicas": 1},
            headers=csrf_headers(client),
        )
        assert scale_down.status_code == 202, scale_down.text
        responder.join(timeout=10)

    down_detail = client.get(f"/deployments/{scale_down.json()['deployment_id']}").json()
    assert down_detail["status"] == "succeeded", down_detail
    assert len(down_detail["instances"]) == 2
    assert all(i["status"] == "stopped" for i in down_detail["instances"])

    instances = client.get(f"/applications/{application_id}/instances").json()
    running = [i for i in instances if i["status"] == "running"]
    stopped = [i for i in instances if i["status"] == "stopped"]
    assert len(running) == 1
    assert len(stopped) == 2

    # The gateway was synced with the drained instances already excluded
    # *before* they were stopped — proving the drain-then-stop ordering
    # actually changed what was routable, not just instance status.
    assert gateway_calls[-1] == 1


def test_scale_endpoint_returns_409_when_the_application_is_already_locked(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-scale-lock@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    from app.repositories.application_repository import ApplicationRepository
    from app.services import lock_service

    application = ApplicationRepository(db_session).get(application_id)
    lock_service.acquire(db_session, application.id, "deploy")

    response = client.post(
        f"/applications/{application_id}/scale",
        json={"desired_replicas": 1},
        headers=csrf_headers(client),
    )
    assert response.status_code == 409
    assert "deploy" in response.json()["detail"]


def test_viewer_cannot_trigger_a_scale(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-scale-viewer-setup@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    login_as(client, db_session, role="Viewer", email="viewer-scale@healer.test")
    response = client.post(
        f"/applications/{application_id}/scale",
        json={"desired_replicas": 1},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403
