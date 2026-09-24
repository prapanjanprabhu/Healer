import uuid

from app.db.models.application import Instance
from app.db.models.enums import InstanceStatus
from app.repositories.application_repository import ApplicationRepository
from tests.support.auth import login_as
from tests.support.csrf import csrf_headers

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


def _register_server(client, db_session) -> str:
    login_as(
        client,
        db_session,
        role="Administrator",
        email=f"admin-logs-{uuid.uuid4().hex[:6]}@healer.test",
    )
    response = client.post(
        "/servers",
        json={
            "name": "logs-target",
            "hostname": f"srv-{uuid.uuid4().hex[:8]}.internal",
            "os": "windows",
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_application(client, server_id: str) -> str:
    config = {**WINDOWS_CONFIG, "server_id": server_id}
    response = client.post("/applications", json=config, headers=csrf_headers(client))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_log_sources_404s_for_unknown_application(client, db_session):
    login_as(client, db_session, role="Viewer", email="viewer-logs-1@healer.test")
    response = client.get(f"/applications/{uuid.uuid4()}/log-sources")
    assert response.status_code == 404


def test_log_sources_lists_a_deployment_entry_with_no_instances(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-logs-1@healer.test")
    application_id = _create_application(client, server_id)

    response = client.get(f"/applications/{application_id}/log-sources")
    assert response.status_code == 200, response.text
    sources = response.json()
    assert sources == [
        {
            "id": "deployment",
            "type": "deployment",
            "label": "Deployment logs (all releases)",
            "instance_id": None,
        }
    ]


def test_log_sources_lists_stdout_stderr_once_an_instance_exists(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-logs-2@healer.test")
    application_id = _create_application(client, server_id)
    application = ApplicationRepository(db_session).get(uuid.UUID(application_id))

    instance = Instance(
        application_id=application.id,
        server_id=uuid.UUID(server_id),
        port=9034,
        status=InstanceStatus.RUNNING,
        service_name=f"Healer-{application.slug}-9034",
    )
    db_session.add(instance)
    db_session.flush()

    response = client.get(f"/applications/{application_id}/log-sources")
    assert response.status_code == 200, response.text
    types = {s["type"] for s in response.json()}
    assert types == {"stdout", "stderr", "deployment"}


def test_get_instance_log_409s_when_agent_not_connected(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-logs-3@healer.test")
    application_id = _create_application(client, server_id)
    application = ApplicationRepository(db_session).get(uuid.UUID(application_id))

    instance = Instance(
        application_id=application.id,
        server_id=uuid.UUID(server_id),
        release_id=None,
        port=9034,
        status=InstanceStatus.RUNNING,
        service_name=f"Healer-{application.slug}-9034",
    )
    db_session.add(instance)
    db_session.flush()

    response = client.get(
        f"/applications/{application_id}/instances/{instance.id}/logs", params={"stream": "stdout"}
    )
    assert response.status_code == 409


def test_get_instance_log_404s_for_unknown_instance(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-logs-4@healer.test")
    application_id = _create_application(client, server_id)

    response = client.get(
        f"/applications/{application_id}/instances/{uuid.uuid4()}/logs", params={"stream": "stdout"}
    )
    assert response.status_code == 404


def test_get_instance_log_rejects_an_invalid_stream_value(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-logs-5@healer.test")
    application_id = _create_application(client, server_id)

    response = client.get(
        f"/applications/{application_id}/instances/{uuid.uuid4()}/logs", params={"stream": "bogus"}
    )
    assert response.status_code == 422
