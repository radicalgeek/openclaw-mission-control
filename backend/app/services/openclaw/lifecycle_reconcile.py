"""Worker handlers for lifecycle reconciliation tasks."""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.constants import (  # noqa: F401 (kept for import compat)
    MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN,
    OFFLINE_AFTER,
)
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.openclaw.lifecycle_queue import decode_lifecycle_task, defer_lifecycle_reconcile
from app.services.queue import QueuedTask

logger = get_logger(__name__)
# Reconcile fans out into multiple openclaw RPC calls (agents.create idempotent
# fail, agents.update, ensure_session, send_message, patch_heartbeat). On the
# Premium NFS-backed gateway state, individual config writes have been observed
# at 24+s under concurrent reconcile load and session-write locks at 30–42s.
# 60s was tighter than the realistic worst-case path; reconciles were timing
# out before they could deliver the wake message, leaving agents stuck with
# last_seen_at=NULL forever. 240s gives realistic headroom; the worker only
# runs one task at a time anyway so the longer slot is acceptable.
_RECONCILE_TIMEOUT_SECONDS = 240.0


def _has_checked_in_since_wake(agent: Agent) -> bool:
    if agent.last_seen_at is None:
        return False
    # An old heartbeat doesn't count — if the agent's last_seen_at is older
    # than OFFLINE_AFTER, it has effectively gone offline since its last
    # wake and needs to be re-woken. Without this guard, agents whose
    # heartbeat loop stopped (gateway restart, model rate limit, etc.) are
    # treated as "still checked in" forever and the reconciler skips them
    # with skip_not_stuck even though the sweep correctly re-queued them.
    if agent.last_seen_at < utcnow() - OFFLINE_AFTER:
        return False
    if agent.last_wake_sent_at is None:
        return True
    return agent.last_seen_at >= agent.last_wake_sent_at


async def process_lifecycle_queue_task(task: QueuedTask) -> None:
    """Re-run lifecycle provisioning when an agent misses post-provision check-in."""
    payload = decode_lifecycle_task(task)
    now = utcnow()

    async with async_session_maker() as session:
        agent = await Agent.objects.by_id(payload.agent_id).first(session)
        if agent is None:
            logger.info(
                "lifecycle.reconcile.skip_missing_agent",
                extra={"agent_id": str(payload.agent_id)},
            )
            return

        # Ignore stale queue messages after a newer lifecycle generation.
        if agent.lifecycle_generation != payload.generation:
            logger.info(
                "lifecycle.reconcile.skip_stale_generation",
                extra={
                    "agent_id": str(agent.id),
                    "queued_generation": payload.generation,
                    "current_generation": agent.lifecycle_generation,
                },
            )
            return

        if _has_checked_in_since_wake(agent):
            logger.info(
                "lifecycle.reconcile.skip_not_stuck",
                extra={"agent_id": str(agent.id), "status": agent.status},
            )
            return

        deadline = agent.checkin_deadline_at or payload.checkin_deadline_at
        if agent.status == "deleting":
            logger.info(
                "lifecycle.reconcile.skip_deleting",
                extra={"agent_id": str(agent.id)},
            )
            return

        if now < deadline:
            delay = max(0.0, (deadline - now).total_seconds())
            if not defer_lifecycle_reconcile(task, delay_seconds=delay):
                msg = "Failed to defer lifecycle reconcile task"
                raise RuntimeError(msg)
            logger.info(
                "lifecycle.reconcile.deferred",
                extra={"agent_id": str(agent.id), "delay_seconds": delay},
            )
            return

        if agent.wake_attempts >= settings.agent_max_wake_attempts:
            agent.status = "offline"
            agent.checkin_deadline_at = None
            agent.last_provision_error = (
                "Agent did not check in after wake; max wake attempts reached"
            )
            agent.updated_at = utcnow()
            session.add(agent)
            await session.commit()
            logger.warning(
                "lifecycle.reconcile.max_attempts_reached",
                extra={
                    "agent_id": str(agent.id),
                    "wake_attempts": agent.wake_attempts,
                    "max_attempts": settings.agent_max_wake_attempts,
                },
            )
            return

        gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
        if gateway is None:
            logger.warning(
                "lifecycle.reconcile.skip_missing_gateway",
                extra={"agent_id": str(agent.id), "gateway_id": str(agent.gateway_id)},
            )
            return
        board: Board | None = None
        if agent.board_id is not None:
            board = await Board.objects.by_id(agent.board_id).first(session)
            if board is None:
                logger.warning(
                    "lifecycle.reconcile.skip_missing_board",
                    extra={"agent_id": str(agent.id), "board_id": str(agent.board_id)},
                )
                return

        # Reset-session policy:
        # - Agents that have heartbeated at least once (last_seen_at is set) —
        #   preserve session. The reconcile fires because they missed the
        #   *latest* check-in window, but their bootstrap completed; resetting
        #   would wipe in-flight task work, memory writes, etc.
        # - Agents that have NEVER heartbeated — reset the session. They're
        #   mid-bootstrap with a stale or rotated token, and the orchestrator
        #   above just re-minted a fresh one. Without a session reset the
        #   agent's running turn keeps using the old token in its env vars and
        #   401s on every API call. Resetting forces openclaw to inject the
        #   newly-rendered workspace/TOOLS.md (with the new token) on next wake.
        reset_session = agent.last_seen_at is None
        orchestrator = AgentLifecycleOrchestrator(session)
        await asyncio.wait_for(
            orchestrator.run_lifecycle(
                gateway=gateway,
                agent_id=agent.id,
                board=board,
                user=None,
                action="update",
                auth_token=None,
                force_bootstrap=False,
                reset_session=reset_session,
                wake=True,
                deliver_wakeup=True,
                wakeup_verb="updated",
                clear_confirm_token=True,
                raise_gateway_errors=True,
            ),
            timeout=_RECONCILE_TIMEOUT_SECONDS,
        )
        logger.info(
            "lifecycle.reconcile.retriggered",
            extra={"agent_id": str(agent.id), "generation": payload.generation},
        )
