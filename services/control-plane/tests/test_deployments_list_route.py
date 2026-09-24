from app.db.models.deployment import Deployment
from app.db.models.enums import DeploymentStatus, ReleaseStatus
from tests.factories import make_application, make_release
from tests.support.auth import login_as


def test_list_deployments_includes_application_name_and_kind(client, db_session):
    login_as(client, db_session, role="Administrator", email="admin-dep-1@healer.test")

    application = make_application(db_session, name="Deployments List Test")
    release = make_release(
        db_session, application=application, ref="v1", status=ReleaseStatus.READY
    )
    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.PENDING,
        instance_count=1,
        kind="deploy",
    )
    db_session.add(deployment)
    db_session.commit()

    listing = client.get("/deployments")
    assert listing.status_code == 200
    entries = [e for e in listing.json() if e["id"] == str(deployment.id)]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["application_name"] == "Deployments List Test"
    assert entry["release_version"] == "v1"
    assert entry["kind"] == "deploy"
    assert entry["status"] == "pending"
    assert "created_at" in entry and "updated_at" in entry


def test_list_deployments_requires_view_permission(client, db_session):
    response = client.get("/deployments")
    assert response.status_code == 401
