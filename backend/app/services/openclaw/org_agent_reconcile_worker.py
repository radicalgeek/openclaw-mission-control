"""Org agent reconcile worker — provisions missing standalone agents for all orgs."""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_maker
from app.services.openclaw.org_agent_reconcile_queue import (
    clear_org_agent_reconcile_lock,
    enqueue_org_agent_reconcile,
)
from app.services.openclaw.org_agent_reconciler import (
    reconcile_all_orgs,
    sweep_stuck_provisioning_agents,
)
from app.services.queue import QueuedTask

logger = get_logger(__name__)


async def process_org_agent_reconcile_task(task: QueuedTask) -> None:
    """Process an org-agent reconcile task: reconcile all orgs, then re-enqueue."""
    logger.info("org_agent_reconcile.start")
    # Release the dedup lock so the self-renewing enqueue at the end of the
    # cycle can claim the slot for the next run.
    clear_org_agent_reconcile_lock()

    async with async_session_maker() as session:
        try:
            await reconcile_all_orgs(session)
        except Exception:
            logger.exception("org_agent_reconcile.error")

        try:
            swept = await sweep_stuck_provisioning_agents(session)
            if swept:
                logger.info("org_agent_reconcile.stuck_sweep_done count=%d", swept)
        except Exception:
            logger.exception("org_agent_reconcile.stuck_sweep_error")

    logger.info("org_agent_reconcile.complete")

    # Re-enqueue for next reconcile cycle
    enqueue_org_agent_reconcile(
        delay_seconds=float(settings.org_agent_reconcile_interval_seconds),
    )
