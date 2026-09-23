import uuid

from app.repositories.application_repository import ApplicationRepository
from app.services import lock_service
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


def _config_for(server_id: str, **overrides) -> dict:
    config = {**WINDOWS_CONFIG, "server_id": server_id}
    config.update(overrides)
    return config


def _register_server(client, db_session) -> str:
    login_as(
        client, db_session, role="Administrator", email=f"admin-{uuid.uuid4().hex[:6]}@healer.test"
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


def test_releases_endpoint_requires_an_active_release_first(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-rel-1@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    response = client.post(f"/applications/{application_id}/releases", headers=csrf_headers(client))
    assert response.status_code == 409
    assert "no active release" in response.json()["detail"]


def test_releases_endpoint_returns_409_when_locked(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-rel-2@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    application = ApplicationRepository(db_session).get(application_id)
    lock_service.acquire(db_session, application.id, "scale")

    response = client.post(f"/applications/{application_id}/releases", headers=csrf_headers(client))
    assert response.status_code == 409
    assert "scale" in response.json()["detail"]


def test_viewer_cannot_trigger_a_release_or_rollback(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-rel-viewer-setup@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    login_as(client, db_session, role="Viewer", email="viewer-rel@healer.test")
    response = client.post(f"/applications/{application_id}/releases", headers=csrf_headers(client))
    assert response.status_code == 403

    response = client.post(
        f"/applications/{application_id}/rollback",
        json={"release_id": str(uuid.uuid4())},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403


def test_list_releases_is_empty_before_any_deploy(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-rel-3@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    response = client.get(f"/applications/{application_id}/releases")
    assert response.status_code == 200
    assert response.json() == []


def test_rollback_rejects_an_application_with_no_active_release(client, db_session):
    server_id = _register_server(client, db_session)
    login_as(client, db_session, role="Operator", email="operator-rel-4@healer.test")
    create = client.post("/applications", json=_config_for(server_id), headers=csrf_headers(client))
    application_id = create.json()["id"]

    response = client.post(
        f"/applications/{application_id}/rollback",
        json={"release_id": str(uuid.uuid4())},
        headers=csrf_headers(client),
    )
    assert response.status_code == 409
    assert "no active release" in response.json()["detail"]
