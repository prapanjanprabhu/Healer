from tests.support.auth import PASSWORD, login_as
from tests.support.csrf import csrf_headers


def test_change_password_succeeds_and_requires_relogin(client, db_session):
    login_as(client, db_session, role="Viewer", email="pw-change-1@healer.test")

    response = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "a-new-strong-password"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text

    # The old session is now cleared; /auth/me should reject it.
    me = client.get("/auth/me")
    assert me.status_code == 401

    relogin = client.post(
        "/auth/login",
        json={"email": "pw-change-1@healer.test", "password": "a-new-strong-password"},
    )
    assert relogin.status_code == 200


def test_change_password_rejects_a_wrong_current_password(client, db_session):
    login_as(client, db_session, role="Viewer", email="pw-change-2@healer.test")

    response = client.post(
        "/auth/change-password",
        json={"current_password": "totally-wrong", "new_password": "a-new-strong-password"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 401
