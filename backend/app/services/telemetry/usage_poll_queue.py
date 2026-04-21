"""Usage poll queue task — periodically snapshots token/cost data from all gateways."""

from __future__ import annotations

from app.core.config import settings
from app.core.time import utcnow
from app.services.queue import QueuedTask, enqueue_task_with_delay
from app.services.queue import requeue_if_failed as generic_requeue_if_failed

TASK_TYPE = "usage_poll"

# How often to poll each gateway, in seconds (default: every 15 minutes)
USAGE_POLL_INTERVAL_SECONDS = 900


def enqueue_usage_poll(*, delay_seconds: float = 0) -> bool:
    """Enqueue a usage snapshot poll task."""
    task = QueuedTask(
        task_type=TASK_TYPE,
        payload={},
        created_at=utcnow(),
        attempts=0,
    )
    return enqueue_task_with_delay(
        task,
        settings.rq_queue_name,
        delay_seconds=delay_seconds,
        redis_url=settings.rq_redis_url,
    )


def requeue_usage_poll_task(task: QueuedTask, *, delay_seconds: float = 0) -> bool:
    return generic_requeue_if_failed(
        task,
        settings.rq_queue_name,
        max_retries=settings.rq_dispatch_max_retries,
        redis_url=settings.rq_redis_url,
        delay_seconds=max(0.0, delay_seconds),
    )
