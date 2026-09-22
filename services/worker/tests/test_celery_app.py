from worker.celery_app import celery_app
from worker.tasks import ping


def test_celery_app_configured_with_redis_broker() -> None:
    assert celery_app.conf.broker_url.startswith("redis://")
    assert celery_app.conf.result_backend.startswith("redis://")


def test_ping_task_registered() -> None:
    assert "worker.ping" in celery_app.tasks


def test_ping_task_runs_synchronously() -> None:
    assert ping() == "pong"
