"""Usage poll queue task — periodically snapshots token/cost data from all gateways."""

from __future__ import annotations

from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.services.queue import QueuedTask, _redis_client, enqueue_task_with_delay
from app.services.queue import requeue_if_failed as generic_requeue_if_failed

TASK_TYPE = "usage_poll"

# How often to poll each gateway, in seconds (default: every 15 minutes)
USAGE_POLL_INTERVAL_SECONDS = 900
_INFLIGHT_KEY = "axiacraft:usage_poll:inflight"

logger = get_logger(__name__)


def enqueue_usage_poll(*, delay_seconds: float = 0) -> bool:
    """Enqueue a usage snapshot poll task."""
    task_id = str(uuid4())
    task = QueuedTask(
        task_type=TASK_TYPE,
        payload={"task_id": task_id},
        created_at=utcnow(),
        attempts=0,
    )
    ttl_seconds = max(60, int(delay_seconds + 60))
    try:
        client = _redis_client(redis_url=settings.rq_redis_url)
        acquired = client.set(_INFLIGHT_KEY, task_id, nx=True, ex=ttl_seconds)
        if not acquired:
            logger.debug("usage_poll.enqueue_skipped reason=already_pending")
            return False
    except Exception:
        logger.warning("usage_poll.dedup_lock_failed", exc_info=True)
    return enqueue_task_with_delay(
        task,
        settings.rq_queue_name,
        delay_seconds=delay_seconds,
        redis_url=settings.rq_redis_url,
    )


def clear_usage_poll_lock(task_id: str | None) -> None:
    if not task_id:
        return
    try:
        client = _redis_client(redis_url=settings.rq_redis_url)
        raw_value = client.get(_INFLIGHT_KEY)
        value = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else raw_value
        if value == task_id:
            client.delete(_INFLIGHT_KEY)
    except Exception:
        logger.warning("usage_poll.lock_clear_failed", exc_info=True)


def is_current_usage_poll_task(task_id: str | None) -> bool:
    """Return whether this task owns the current usage-poll slot.

    Older releases could enqueue many duplicate usage polls. Keep one owner and
    let stale queue entries drain quickly instead of monopolizing the worker.
    """
    try:
        client = _redis_client(redis_url=settings.rq_redis_url)
        raw_value = client.get(_INFLIGHT_KEY)
    except Exception:
        logger.warning("usage_poll.lock_check_failed", exc_info=True)
        return True

    value = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else raw_value
    if value is None:
        return True
    return task_id == value


def requeue_usage_poll_task(task: QueuedTask, *, delay_seconds: float = 0) -> bool:
    return generic_requeue_if_failed(
        task,
        settings.rq_queue_name,
        max_retries=settings.rq_dispatch_max_retries,
        redis_url=settings.rq_redis_url,
        delay_seconds=max(0.0, delay_seconds),
    )
