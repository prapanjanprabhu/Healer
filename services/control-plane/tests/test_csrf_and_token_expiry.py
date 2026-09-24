"""Two real gaps flagged in Phase 15's test-coverage audit: CSRF enforcement
was only ever exercised on /auth/refresh and /auth/logout (every other test
always supplies the header, so nothing proved a *business* mutation route
rejects a request missing it), and no test proved an access token past its
TTL is actually rejected — only refresh-token rotation/replay was tested.
"""

from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME
from app.core.security import ACCESS_TOKEN_TYPE
from tests.support.auth import login_as
from tests.support.csrf import csrf_headers

WINDOWS_CONFIG = {
    "version": 1,
    "name": "CSRF Test App",
    "adapter": "windows-waitress-service",
    "source": {"type": "folder", "location": "C:\\HealerTest\\erp"},
    "windows": {
        "python_executable": "C:\\Python\\python.exe",
        "wsgi_module": "erp.wsgi",
        "settings_module": "erp.settings",
    },
    "health": {"path": "/health/"},
    "ports": {"start": 9700, "end": 9705},
    "secrets": [],
}


def test_scale_is_rejected_without_a_csrf_header(client, db_session):
    login_as(client, db_session, role="Administrator", email="csrf-scale@healer.test")
    create = client.post("/applications", json=WINDOWS_CONFIG, headers=csrf_headers(client))
    assert create.status_code == 201

    # Deliberately no X-CSRF-Token header.
    response = client.post(
        f"/applications/{create.json()['id']}/scale", json={"desired_replicas": 1}
    )
    assert response.status_code == 403


def test_secret_set_is_rejected_without_a_csrf_header(client, db_session):
    login_as(client, db_session, role="Administrator", email="csrf-secret@healer.test")
    create = client.post("/applications", json=WINDOWS_CONFIG, headers=csrf_headers(client))
    assert create.status_code == 201

    response = client.post(
        f"/applications/{create.json()['id']}/secrets", json={"key": "X", "value": "y"}
    )
    assert response.status_code == 403


def test_application_create_is_rejected_without_a_csrf_header(client, db_session):
    login_as(client, db_session, role="Administrator", email="csrf-create@healer.test")
    response = client.post("/applications", json=WINDOWS_CONFIG)
    assert response.status_code == 403


def test_an_expired_access_token_is_rejected_by_a_protected_route(client, db_session):
    user = login_as(client, db_session, role="Viewer", email="expired-token@healer.test")

    now = datetime.now(UTC)
    expired_payload = {
        "sub": str(user.id),
        "roles": ["Viewer"],
        "type": ACCESS_TOKEN_TYPE,
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),  # already expired
    }
    expired_token = jwt.encode(
        expired_payload, settings.control_plane_secret_key, algorithm="HS256"
    )
    client.cookies.set(ACCESS_COOKIE_NAME, expired_token)

    response = client.get("/auth/me")
    assert response.status_code == 401


def test_a_token_with_the_wrong_signature_is_rejected(client, db_session):
    login_as(client, db_session, role="Viewer", email="bad-sig@healer.test")

    now = datetime.now(UTC)
    payload = {
        "sub": "00000000-0000-0000-0000-000000000000",
        "roles": ["Administrator"],
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    forged_token = jwt.encode(payload, "not-the-real-secret-key", algorithm="HS256")
    client.cookies.set(ACCESS_COOKIE_NAME, forged_token)

    response = client.get("/auth/me")
    assert response.status_code == 401
