"""Administrator-only database management dashboard (app/api/routes/admin_db.py,
app/services/db_admin_service.py, app/domain/db_admin_registry.py) —
phpMyAdmin-style full CRUD on every table. Covers access control, that the
two narrow technical exceptions (sensitive hash/ciphertext columns, primary
keys, composite-PK tables) hold, and that domains.hostname/cert_path edits
still reject the same Nginx-injection/path-traversal payloads the normal
write path does, since this is a second path that writes those columns.
"""

from app.db.models.domain import Domain
from tests.factories import make_application, make_release, make_server, make_user
from tests.support.auth import login_as
from tests.support.csrf import csrf_headers


def test_non_administrator_cannot_list_tables(client, db_session):
    login_as(client, db_session, role="Operator", email="operator-db-1@healer.test")
    response = client.get("/admin/db/tables")
    assert response.status_code == 403


def test_administrator_can_list_tables_and_every_table_is_editable_except_composite_pk(
    client, db_session
):
    login_as(client, db_session, role="Administrator", email="admin-db-1@healer.test")
    response = client.get("/admin/db/tables")
    assert response.status_code == 200
    tables = {t["name"]: t for t in response.json()}
    assert "alembic_version" not in tables

    # Full CRUD by default, including tables a curated allow-list would
    # have kept view-only (users, deployments, audit_logs).
    for name in ("servers", "domains", "users", "deployments", "audit_logs", "secret_records"):
        assert tables[name]["editable"] is True, name
        assert tables[name]["deletable"] is True, name

    # user_roles has a composite (user_id, role_id) primary key — no single
    # id to address a row by, so it's listable but not editable/deletable.
    assert tables["user_roles"]["single_column_pk"] is None
    assert tables["user_roles"]["editable"] is False
    assert tables["user_roles"]["deletable"] is False


def test_password_hash_is_redacted_and_not_editable(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-db-2@healer.test")
    user = make_user(db_session, email="redact-target@healer.test")

    listing = client.get("/admin/db/tables/users/rows")
    row = next(r for r in listing.json()["rows"] if r["email"] == "redact-target@healer.test")
    assert row["password_hash"] == "[REDACTED]"

    tables = {t["name"]: t for t in client.get("/admin/db/tables").json()}
    editable_names = {c["name"] for c in tables["users"]["editable_columns"]}
    assert "password_hash" not in editable_names
    assert "email" in editable_names  # everything else on users IS editable now

    response = client.patch(
        f"/admin/db/tables/users/rows/{user.id}",
        json={"changes": {"password_hash": "whatever"}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 400


def test_editing_a_non_sensitive_column_on_users_succeeds(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-db-3@healer.test")
    user = make_user(db_session, email="editable-field@healer.test")

    response = client.patch(
        f"/admin/db/tables/users/rows/{user.id}",
        json={"changes": {"email": "changed-via-admin-db@healer.test"}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    assert response.json()["email"] == "changed-via-admin-db@healer.test"


def test_agent_command_env_secrets_are_redacted_and_payload_is_not_editable(client, db_session):
    from app.db.models.agent import Agent, AgentCommand
    from app.db.models.enums import AgentCommandType

    login_as(client, db_session, role="Administrator", email="admin-db-4@healer.test")
    server = make_server(db_session)
    agent = Agent(server_id=server.id, agent_version="1.0.0")
    db_session.add(agent)
    db_session.flush()
    command = AgentCommand(
        agent_id=agent.id,
        command_type=AgentCommandType.START_INSTANCE,
        payload={
            "adapter": "linux-docker",
            "linux": {"env": {"DATABASE_PASSWORD": "super-secret"}, "internal_port": 8000},
        },
        idempotency_key="admin-db-test-key",
    )
    db_session.add(command)
    db_session.flush()

    response = client.get(f"/admin/db/tables/agent_commands/rows/{command.id}")
    payload = response.json()["payload"]
    assert payload["linux"]["env"]["DATABASE_PASSWORD"] == "[REDACTED]"
    assert payload["adapter"] == "linux-docker"  # non-secret fields stay visible

    edit_attempt = client.patch(
        f"/admin/db/tables/agent_commands/rows/{command.id}",
        json={"changes": {"payload": {"adapter": "windows-waitress-service"}}},
        headers=csrf_headers(client),
    )
    assert edit_attempt.status_code == 400  # can't save back a value we showed redacted

    # A non-redacted column on the same table is still editable.
    error_edit = client.patch(
        f"/admin/db/tables/agent_commands/rows/{command.id}",
        json={"changes": {"error": "manually annotated by an administrator"}},
        headers=csrf_headers(client),
    )
    assert error_edit.status_code == 200
    assert error_edit.json()["error"] == "manually annotated by an administrator"


def test_server_name_is_editable_and_change_is_audited(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-db-5@healer.test")
    server = make_server(db_session, name="old-name")

    response = client.patch(
        f"/admin/db/tables/servers/rows/{server.id}",
        json={"changes": {"name": "new-name"}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "new-name"

    audit = client.get("/audit-log")
    actions = [entry["action"] for entry in audit.json()]
    assert "admin.db_row_updated" in actions


def test_domain_hostname_edit_rejects_nginx_config_injection(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-db-6@healer.test")
    application = make_application(db_session)
    domain = Domain(application_id=application.id, hostname="safe.example.com")
    db_session.add(domain)
    db_session.flush()

    response = client.patch(
        f"/admin/db/tables/domains/rows/{domain.id}",
        json={"changes": {"hostname": "evil.com; location /leak { alias /etc/; } #"}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 400


def test_domain_cert_path_edit_rejects_path_traversal(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-db-7@healer.test")
    application = make_application(db_session)
    domain = Domain(application_id=application.id, hostname="safe2.example.com")
    db_session.add(domain)
    db_session.flush()

    response = client.patch(
        f"/admin/db/tables/domains/rows/{domain.id}",
        json={"changes": {"cert_path": "/etc/healer/certs/../../../etc/shadow"}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 400


def test_servers_table_is_deletable(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-db-8@healer.test")
    server = make_server(db_session)

    response = client.delete(f"/admin/db/tables/servers/rows/{server.id}", headers=csrf_headers(client))
    assert response.status_code == 204

    listing = client.get("/admin/db/tables/servers/rows")
    ids = {row["id"] for row in listing.json()["rows"]}
    assert str(server.id) not in ids


def test_deployments_table_is_now_deletable_full_crud(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-db-9@healer.test")
    application = make_application(db_session)
    release = make_release(db_session, application=application)

    from app.db.models.deployment import Deployment
    from app.db.models.enums import DeploymentStatus

    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.SUCCEEDED,
        kind="deploy",
        instance_count=1,
    )
    db_session.add(deployment)
    db_session.flush()

    response = client.delete(
        f"/admin/db/tables/deployments/rows/{deployment.id}", headers=csrf_headers(client)
    )
    assert response.status_code == 204


def test_cannot_edit_the_primary_key_column(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-db-10@healer.test")
    server = make_server(db_session)

    tables = {t["name"]: t for t in client.get("/admin/db/tables").json()}
    editable_names = {c["name"] for c in tables["servers"]["editable_columns"]}
    assert "id" not in editable_names

    response = client.patch(
        f"/admin/db/tables/servers/rows/{server.id}",
        json={"changes": {"id": "00000000-0000-0000-0000-000000000000"}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 400
