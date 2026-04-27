"""Org agent reconcile queue task — periodically provisions standalone agents for all orgs."""

from __future__ import annotations

from app.core.config import settings
from app.core.time import utcnow
from app.services.queue import QueuedTask, enqueue_task_with_delay
from app.services.queue import requeue_if_failed as generic_requeue_if_failed

TASK_TYPE = "org_agent_reconcile"


def enqueue_org_agent_reconcile(*, delay_seconds: float = 0) -> bool:
    """Enqueue an org-agent reconciliation task."""
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


def requeue_org_agent_reconcile_task(task: QueuedTask, *, delay_seconds: float = 0) -> bool:
    return generic_requeue_if_failed(
        task,
        settings.rq_queue_name,
        max_retries=settings.rq_dispatch_max_retries,
        redis_url=settings.rq_redis_url,
        delay_seconds=max(0.0, delay_seconds),
    )
