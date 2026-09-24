from tests.support.auth import login_as


def test_audit_log_requires_administrator(client, db_session):
    login_as(client, db_session, role="Operator", email="operator-audit-1@healer.test")
    response = client.get("/audit-log")
    assert response.status_code == 403


def test_administrator_sees_their_own_login_recorded(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-audit-1@healer.test")
    response = client.get("/audit-log", params={"action": "auth.login_succeeded", "limit": 500})
    assert response.status_code == 200
    body = response.json()
    assert any(e["actor_email"] == "admin-audit-1@healer.test" for e in body)


def test_audit_log_filters_by_action(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-audit-2@healer.test")
    response = client.get("/audit-log", params={"action": "this-action-never-happened"})
    assert response.status_code == 200
    assert response.json() == []
