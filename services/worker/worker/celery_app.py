from celery import Celery

from worker.config import settings

celery_app = Celery(
    "healer_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Required on Celery 5.4+ so the worker retries connecting to Redis at
    # startup instead of failing hard if Redis isn't ready yet (compose
    # dependency ordering only guarantees the container health, not the
    # instant the client connects).
    broker_connection_retry_on_startup=True,
)
