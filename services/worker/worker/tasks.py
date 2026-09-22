from worker.celery_app import celery_app


@celery_app.task(name="worker.ping")
def ping() -> str:
    """Trivial task used to verify the worker is up and connected to Redis.

    Real jobs (deploy, rollback, restart, port allocation, health-driven
    remediation) land in a later phase alongside the Control Plane's
    deployment behavior.
    """
    return "pong"
