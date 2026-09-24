from app.db.models.application import Instance
from app.db.models.deployment import Deployment
from app.db.models.enums import DeploymentStatus, InstanceStatus
from app.services import lock_service, reconcile_service
from tests.factories import make_application, make_release, make_server


def test_reconcile_fails_a_stuck_in_progress_deployment_and_releases_its_lock(db_session):
    application = make_application(db_session)
    release = make_release(db_session, application=application)
    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.IN_PROGRESS,
        instance_count=1,
    )
    db_session.add(deployment)
    db_session.flush()
    lock_service.acquire(db_session, application.id, "deploy")

    reconciled = reconcile_service.reconcile_stuck_deployments(db_session)

    assert reconciled == 1
    db_session.refresh(deployment)
    db_session.refresh(application)
    assert deployment.status == DeploymentStatus.FAILED
    assert deployment.failure_reason == reconcile_service.STUCK_DEPLOYMENT_REASON
    assert application.operation_lock is None


def test_reconcile_leaves_terminal_deployments_untouched(db_session):
    application = make_application(db_session)
    release = make_release(db_session, application=application)
    deployment = Deployment(
        application_id=application.id,
        release_id=release.id,
        status=DeploymentStatus.SUCCEEDED,
        instance_count=1,
    )
    db_session.add(deployment)
    db_session.flush()

    reconciled = reconcile_service.reconcile_stuck_deployments(db_session)

    assert reconciled == 0
    db_session.refresh(deployment)
    assert deployment.status == DeploymentStatus.SUCCEEDED


def test_reconcile_is_a_noop_when_nothing_is_stuck(db_session):
    assert reconcile_service.reconcile_stuck_deployments(db_session) == 0


def test_reconcile_fails_instances_stuck_in_a_transient_state(db_session):
    server = make_server(db_session)
    application = make_application(db_session, server_id=server.id)
    stuck_starting = Instance(
        application_id=application.id, server_id=server.id, port=9800,
        status=InstanceStatus.STARTING, service_name="Healer-x-9800",
    )
    stuck_draining = Instance(
        application_id=application.id, server_id=server.id, port=9801,
        status=InstanceStatus.DRAINING, service_name="Healer-x-9801",
    )
    running = Instance(
        application_id=application.id, server_id=server.id, port=9802,
        status=InstanceStatus.RUNNING, service_name="Healer-x-9802",
    )
    db_session.add_all([stuck_starting, stuck_draining, running])
    db_session.flush()

    reconciled = reconcile_service.reconcile_stuck_instances(db_session)

    assert reconciled == 2
    db_session.refresh(stuck_starting)
    db_session.refresh(stuck_draining)
    db_session.refresh(running)
    assert stuck_starting.status == InstanceStatus.FAILED
    assert stuck_starting.failure_reason == reconcile_service.STUCK_INSTANCE_REASON
    assert stuck_draining.status == InstanceStatus.FAILED
    assert running.status == InstanceStatus.RUNNING  # untouched
