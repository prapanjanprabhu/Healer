import uuid

from app.db.models.application import Instance
from app.db.models.enums import InstanceStatus
from app.repositories.application_repository import ApplicationRepository
from tests.support.auth import login_as
from tests.support.csrf import csrf_headers

WINDOWS_CONFIG = {
    "version": 1,
    "name": "Instance Route Test",
    "adapter": "windows-waitress-service",
    "source": {"type": "folder", "location": "C:\\HealerTest\\erp"},
    "windows": {
        "python_executable": "C:\\Python\\python.exe",
        "wsgi_module": "erp.wsgi",
        "settings_module": "erp.settings",
    },
    "health": {"path": "/health/"},
    "ports": {"start": 9500, "end": 9505},
    "secrets": [],
}


def _register_server(client, db_session) -> str:
    login_as(
        client,
        db_session,
        role="Administrator",
        email=f"admin-inst-{uuid.uuid4().hex[:6]}@healer.test",
    )
    response = client.post(
        "/servers",
        json={
            "name": "target",
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


def test_restart_requires_restart_permission(client, db_session):
    server_id = _register_server(client, db_session)
    application_id = _create_application(client, server_id)
    login_as(client, db_session, role="Viewer", email="viewer-inst-1@healer.test")

    response = client.post(
        f"/applications/{application_id}/instances/{uuid.uuid4()}/restart",
        headers=csrf_headers(client),
    )
    assert response.status_code == 403


def test_restart_404s_for_unknown_instance(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-inst-1@healer.test")
    application_id = _create_application(client, server_id)

    response = client.post(
        f"/applications/{application_id}/instances/{uuid.uuid4()}/restart",
        headers=csrf_headers(client),
    )
    assert response.status_code == 404


def test_stop_409s_when_agent_not_connected(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-inst-2@healer.test")
    application_id = _create_application(client, server_id)
    application = ApplicationRepository(db_session).get(uuid.UUID(application_id))

    instance = Instance(
        application_id=application.id,
        server_id=uuid.UUID(server_id),
        port=9500,
        status=InstanceStatus.RUNNING,
        service_name=f"Healer-{application.slug}-9500",
    )
    db_session.add(instance)
    db_session.flush()

    response = client.post(
        f"/applications/{application_id}/instances/{instance.id}/stop", headers=csrf_headers(client)
    )
    assert response.status_code == 409
