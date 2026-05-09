"""Org agent reconcile queue task — periodically provisions standalone agents for all orgs."""

from __future__ import annotations

from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.services.queue import QueuedTask, _redis_client, enqueue_task_with_delay
from app.services.queue import requeue_if_failed as generic_requeue_if_failed

TASK_TYPE = "org_agent_reconcile"

# Lock key used for in-flight dedup. Multiple call sites enqueue this task
# (backend startup seed, gateway create, organization create, the worker's
# self-renewing tail). Without dedup we accumulate duplicates in Redis and
# the sweep ends up firing every ~1-2 min instead of every 5 min, which
# rapidly cycles agents through the lifecycle reconcile loop.
_INFLIGHT_KEY = "axiacraft:org_agent_reconcile:inflight"

logger = get_logger(__name__)


def enqueue_org_agent_reconcile(*, delay_seconds: float = 0) -> bool:
    """Enqueue an org-agent reconciliation task.

    Idempotent — returns False if a task is already pending in Redis.
    Uses ``SET NX EX`` with a TTL slightly longer than ``delay_seconds`` (or
    a default 60s for delay=0) so the lock auto-expires if the worker dies
    before clearing it. The worker explicitly clears the lock at the start
    of each task run so the next ``enqueue_org_agent_reconcile`` (called at
    the end of the same cycle) can take the slot.
    """
    task_id = str(uuid4())
    task = QueuedTask(
        task_type=TASK_TYPE,
        payload={"task_id": task_id},
        created_at=utcnow(),
        attempts=0,
    )

    # Dedup. Lock TTL is delay + grace so a stuck worker doesn't permanently
    # block. Minimum 60s for the immediate-enqueue case so startup-seed +
    # tail-renew don't race.
    ttl_seconds = max(60, int(delay_seconds + 60))
    try:
        client = _redis_client(redis_url=settings.rq_redis_url)
        acquired = client.set(_INFLIGHT_KEY, task_id, nx=True, ex=ttl_seconds)
        if not acquired:
            logger.debug(
                "org_agent_reconcile.enqueue_skipped reason=already_pending",
            )
            return False
    except Exception:
        # Best-effort dedup. If Redis is misbehaving, fall through and let
        # the queue accept the task — the worker's stale-generation guards
        # will still skip duplicate work, just less efficiently.
        logger.warning("org_agent_reconcile.dedup_lock_failed", exc_info=True)

    return enqueue_task_with_delay(
        task,
        settings.rq_queue_name,
        delay_seconds=delay_seconds,
        redis_url=settings.rq_redis_url,
    )


def clear_org_agent_reconcile_lock(task_id: str | None) -> None:
    """Release the in-flight lock if this task owns it.

    Legacy already-queued tasks may not have a task id. Those tasks must not
    clear a newer scheduled task's lock, or they can create a chain of duplicate
    org-reconcile runs that starves agent lifecycle work.
    """
    if not task_id:
        return
    try:
        client = _redis_client(redis_url=settings.rq_redis_url)
        raw_value = client.get(_INFLIGHT_KEY)
        value = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else raw_value
        if value == task_id:
            client.delete(_INFLIGHT_KEY)
    except Exception:
        logger.warning("org_agent_reconcile.lock_clear_failed", exc_info=True)


def requeue_org_agent_reconcile_task(task: QueuedTask, *, delay_seconds: float = 0) -> bool:
    return generic_requeue_if_failed(
        task,
        settings.rq_queue_name,
        max_retries=settings.rq_dispatch_max_retries,
        redis_url=settings.rq_redis_url,
        delay_seconds=max(0.0, delay_seconds),
    )
