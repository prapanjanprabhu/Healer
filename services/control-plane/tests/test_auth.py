from app.core.cookies import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.db.models.audit import AuditLog
from app.db.models.deployment import Deployment
from app.db.models.enums import DeploymentStatus
from tests.factories import DEFAULT_TEST_PASSWORD, make_application, make_release, make_user

PASSWORD = DEFAULT_TEST_PASSWORD


def _csrf_headers(client) -> dict:
    token = client.cookies.get(CSRF_COOKIE_NAME)
    assert token is not None, "expected a CSRF cookie to be set after login"
    return {"X-CSRF-Token": token}


def _make_deployment(db_session) -> Deployment:
    application = make_application(db_session)
    release = make_release(db_session, application=application)
    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.PENDING,
        instance_count=1,
    )
    db_session.add(deployment)
    db_session.flush()
    return deployment


# --- login -------------------------------------------------------------------


def test_login_success_sets_cookies_and_returns_user(client, db_session):
    user = make_user(db_session, email="admin@healer.test", role_names=("Administrator",))

    response = client.post("/auth/login", json={"email": user.email, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == user.email
    assert body["roles"] == ["Administrator"]
    assert client.cookies.get(ACCESS_COOKIE_NAME) is not None
    assert client.cookies.get(REFRESH_COOKIE_NAME) is not None
    assert client.cookies.get(CSRF_COOKIE_NAME) is not None


def test_login_failure_wrong_password(client, db_session):
    user = make_user(db_session, email="viewer@healer.test", role_names=("Viewer",))

    response = client.post("/auth/login", json={"email": user.email, "password": "wrong"})

    assert response.status_code == 401
    assert client.cookies.get(ACCESS_COOKIE_NAME) is None


def test_login_failure_unknown_email(client):
    response = client.post(
        "/auth/login", json={"email": "nobody@healer.test", "password": PASSWORD}
    )
    assert response.status_code == 401


def test_login_records_audit_entries_without_leaking_the_password(client, db_session):
    make_user(db_session, email="audited@healer.test", role_names=("Viewer",))

    client.post("/auth/login", json={"email": "audited@healer.test", "password": "wrong"})
    client.post("/auth/login", json={"email": "audited@healer.test", "password": PASSWORD})

    entries = db_session.query(AuditLog).filter(AuditLog.target_type == "user").all()
    actions = {entry.action for entry in entries}
    assert "auth.login_failed" in actions
    assert "auth.login_succeeded" in actions

    dump = str([(e.action, e.detail) for e in entries])
    assert PASSWORD not in dump
    assert "wrong" not in dump


# --- me ------------------------------------------------------------------------


def test_me_requires_authentication(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user_after_login(client, db_session):
    user = make_user(db_session, email="operator@healer.test", role_names=("Operator",))
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})

    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == user.email
    assert response.json()["roles"] == ["Operator"]


# --- refresh ---------------------------------------------------------------------


def test_refresh_requires_csrf_header(client, db_session):
    user = make_user(db_session, email="csrf@healer.test", role_names=("Viewer",))
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})

    response = client.post("/auth/refresh")  # no X-CSRF-Token header
    assert response.status_code == 403


def test_refresh_rotates_tokens_and_rejects_replay_of_the_old_one(client, db_session):
    user = make_user(db_session, email="rotate@healer.test", role_names=("Viewer",))
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})

    old_refresh = client.cookies.get(REFRESH_COOKIE_NAME)
    response = client.post("/auth/refresh", headers=_csrf_headers(client))
    assert response.status_code == 200

    new_refresh = client.cookies.get(REFRESH_COOKIE_NAME)
    assert new_refresh != old_refresh

    # Replaying the now-revoked old refresh token must fail.
    client.cookies.set(REFRESH_COOKIE_NAME, old_refresh)
    replay = client.post("/auth/refresh", headers=_csrf_headers(client))
    assert replay.status_code == 401

    # Reuse detection revokes every session for the user, including the one
    # the rotation above just created — so even the *current* refresh token
    # no longer works.
    client.cookies.set(REFRESH_COOKIE_NAME, new_refresh)
    after_reuse = client.post("/auth/refresh", headers=_csrf_headers(client))
    assert after_reuse.status_code == 401


# --- logout ------------------------------------------------------------------------


def test_logout_clears_cookies_and_revokes_the_session(client, db_session):
    user = make_user(db_session, email="logout@healer.test", role_names=("Viewer",))
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    refresh_token = client.cookies.get(REFRESH_COOKIE_NAME)
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)

    response = client.post("/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 200
    assert client.cookies.get(ACCESS_COOKIE_NAME) is None
    assert client.cookies.get(REFRESH_COOKIE_NAME) is None
    assert client.cookies.get(CSRF_COOKIE_NAME) is None

    # Simulate a client that still holds the old (now-revoked) cookies — e.g.
    # another tab that hasn't picked up the Set-Cookie deletion yet. Restore
    # both the refresh and CSRF cookies so the request passes the CSRF check
    # and actually exercises "is this refresh session still valid" — the
    # revoked session must be rejected, not just "cookie was deleted".
    client.cookies.set(REFRESH_COOKIE_NAME, refresh_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    refresh_after_logout = client.post("/auth/refresh", headers={"X-CSRF-Token": csrf_token})
    assert refresh_after_logout.status_code == 401


def test_logout_is_audited(client, db_session):
    user = make_user(db_session, email="logout2@healer.test", role_names=("Viewer",))
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    client.post("/auth/logout", headers=_csrf_headers(client))

    # Scoped to this user's id rather than a blanket count of every
    # "auth.logout" row — a real audit table is never empty, and the test
    # shouldn't assume it starts that way.
    entries = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "auth.logout", AuditLog.target_id == str(user.id))
        .all()
    )
    assert len(entries) == 1
    assert entries[0].target_id == str(user.id)


# --- role-based authorization ------------------------------------------------------


def test_viewer_can_list_deployments_but_cannot_start_one(client, db_session):
    deployment = _make_deployment(db_session)
    user = make_user(db_session, email="viewer2@healer.test", role_names=("Viewer",))
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})

    list_response = client.get("/deployments")
    assert list_response.status_code == 200

    deploy_response = client.post(
        f"/deployments/{deployment.id}/actions/deploy", headers=_csrf_headers(client)
    )
    assert deploy_response.status_code == 403


def test_operator_can_start_a_deployment(client, db_session):
    deployment = _make_deployment(db_session)
    user = make_user(db_session, email="operator2@healer.test", role_names=("Operator",))
    client.post("/auth/login", json={"email": user.email, "password": PASSWORD})

    response = client.post(
        f"/deployments/{deployment.id}/actions/deploy", headers=_csrf_headers(client)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_unauthenticated_request_cannot_start_a_deployment(client, db_session):
    deployment = _make_deployment(db_session)
    response = client.post(f"/deployments/{deployment.id}/actions/deploy")
    assert response.status_code == 401
