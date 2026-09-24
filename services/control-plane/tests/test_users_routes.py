from tests.support.auth import login_as
from tests.support.csrf import csrf_headers


def test_list_users_requires_manage_users_permission(client, db_session):
    login_as(client, db_session, role="Operator", email="operator-users-1@healer.test")
    response = client.get("/users")
    assert response.status_code == 403


def test_administrator_can_list_and_create_users(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-users-1@healer.test")

    response = client.post(
        "/users",
        json={
            "email": "brand-new@healer.test",
            "password": "a-strong-password",
            "roles": ["Viewer"],
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "brand-new@healer.test"
    assert body["roles"] == ["Viewer"]
    assert body["is_active"] is True

    listing = client.get("/users")
    assert listing.status_code == 200
    emails = {u["email"] for u in listing.json()}
    assert "brand-new@healer.test" in emails


def test_create_user_rejects_duplicate_email(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-users-2@healer.test")
    payload = {
        "email": "dup-route@healer.test",
        "password": "a-strong-password",
        "roles": ["Viewer"],
    }
    first = client.post("/users", json=payload, headers=csrf_headers(client))
    assert first.status_code == 201
    second = client.post("/users", json=payload, headers=csrf_headers(client))
    assert second.status_code == 409


def test_administrator_can_change_another_users_roles(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-users-3@healer.test")
    create = client.post(
        "/users",
        json={
            "email": "role-target@healer.test",
            "password": "a-strong-password",
            "roles": ["Viewer"],
        },
        headers=csrf_headers(client),
    )
    user_id = create.json()["id"]

    response = client.patch(
        f"/users/{user_id}/roles", json={"roles": ["Operator"]}, headers=csrf_headers(client)
    )
    assert response.status_code == 200
    assert response.json()["roles"] == ["Operator"]


def test_administrator_cannot_remove_their_own_administrator_role(client, db_session):
    admin = login_as(client, db_session, role="Administrator", email="admin-users-4@healer.test")

    response = client.patch(
        f"/users/{admin.id}/roles", json={"roles": ["Viewer"]}, headers=csrf_headers(client)
    )
    assert response.status_code == 409


def test_administrator_cannot_deactivate_their_own_account(client, db_session):
    admin = login_as(client, db_session, role="Administrator", email="admin-users-5@healer.test")

    response = client.post(f"/users/{admin.id}/deactivate", headers=csrf_headers(client))
    assert response.status_code == 409


def test_deactivate_and_reactivate_another_user(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-users-6@healer.test")
    create = client.post(
        "/users",
        json={"email": "toggle@healer.test", "password": "a-strong-password", "roles": ["Viewer"]},
        headers=csrf_headers(client),
    )
    user_id = create.json()["id"]

    deactivated = client.post(f"/users/{user_id}/deactivate", headers=csrf_headers(client))
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    reactivated = client.post(f"/users/{user_id}/activate", headers=csrf_headers(client))
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True


def test_list_role_names_returns_the_fixed_set(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-users-7@healer.test")
    response = client.get("/users/roles")
    assert response.status_code == 200
    assert response.json() == ["Administrator", "Operator", "Viewer"]
