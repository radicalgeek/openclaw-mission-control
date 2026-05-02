"""Gateway messaging service for planning sessions."""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import settings
from app.core.logging import TRACE_LEVEL
from app.core.time import utcnow
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.plans import Plan
from app.services.openclaw.constants import OFFLINE_AFTER
from app.services.openclaw.coordination_service import AbstractGatewayMessagingService
from app.services.openclaw.exceptions import GatewayOperation, map_gateway_error_to_http_exception
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.openclaw.shared import GatewayAgentIdentity

PLAN_DISPATCH_OPERATION = GatewayOperation.LEAD_MESSAGE_DISPATCH

# Best-effort wake of an idle standalone agent before dispatching a prompt.
# Bounded so a stuck wake cannot block the dispatch path indefinitely.
_STANDALONE_WAKE_TIMEOUT_SECONDS = 30.0

# Persisted agent.status values that mean another writer is already mutating
# the lifecycle; if we see one, leave the agent alone so we don't race.
_LIFECYCLE_BUSY_STATUSES = frozenset({"provisioning", "updating", "deleting"})


def _is_standalone_idle(agent: Agent) -> bool:
    """True when a standalone agent looks idle and would benefit from a wake.

    Skips agents whose persisted status indicates another lifecycle pass is
    already in flight, and agents that have heartbeated within
    ``OFFLINE_AFTER``. Treats agents that have never heartbeated
    (``last_seen_at is None``) as idle so first-use after deploy still wakes
    them.
    """
    if agent.status in _LIFECYCLE_BUSY_STATUSES:
        return False
    last_seen = agent.last_seen_at
    if last_seen is None:
        return True
    return (utcnow() - last_seen) > OFFLINE_AFTER


class PlanningMessagingService(AbstractGatewayMessagingService):
    """Gateway message dispatch helpers for planning session routes."""

    async def _resolve_org_agent_session(
        self,
        agent_id_setting: str,
    ) -> tuple[str, str] | None:
        """Look up an org-wide standalone agent by configured ID.

        Returns ``(session_key, agent_name)`` if the agent exists and has an
        OpenClaw session, ``None`` otherwise (caller should fall back to the
        board lead).

        Standalone agents go offline when idle and OpenClaw will accept a
        ``send_message`` to a dead session without surfacing an error, so the
        prompt would be silently dropped. Before returning, best-effort wake
        the agent if its heartbeat is stale; this matches the pattern used
        for board-attached agents whose lifecycle keeps them warm.
        """
        if not agent_id_setting:
            return None
        try:
            agent_uuid = UUID(agent_id_setting)
        except ValueError:
            self.logger.warning(
                "planning.org_agent.invalid_uuid setting=%s",
                agent_id_setting,
            )
            return None
        agent = await Agent.objects.by_id(agent_uuid).first(self.session)
        if agent is None or not agent.openclaw_session_id:
            return None
        await self._ensure_standalone_awake(agent)
        return agent.openclaw_session_id, agent.name

    async def _ensure_standalone_awake(self, agent: Agent) -> None:
        """Wake a standalone agent if it appears idle.

        Skips when the agent is mid-lifecycle (``provisioning`` / ``updating``
        / ``deleting``) or has heartbeated within ``OFFLINE_AFTER``. Otherwise
        runs an ``update`` lifecycle pass that re-establishes the gateway
        session and delivers a wakeup. Errors are logged but never raised:
        the caller still attempts to dispatch — if the agent stays asleep,
        the dispatch will surface the failure on its own.
        """
        if not _is_standalone_idle(agent):
            return

        gateway = await Gateway.objects.by_id(agent.gateway_id).first(self.session)
        if gateway is None or not gateway.url:
            self.logger.warning(
                "planning.standalone_wake.skip_missing_gateway agent_id=%s",
                agent.id,
            )
            return

        try:
            await asyncio.wait_for(
                AgentLifecycleOrchestrator(self.session).run_lifecycle(
                    gateway=gateway,
                    agent_id=agent.id,
                    board=None,
                    user=None,
                    action="update",
                    auth_token=None,
                    force_bootstrap=False,
                    reset_session=True,
                    wake=True,
                    deliver_wakeup=True,
                    wakeup_verb="dispatched",
                    clear_confirm_token=True,
                    raise_gateway_errors=False,
                ),
                timeout=_STANDALONE_WAKE_TIMEOUT_SECONDS,
            )
            self.logger.info(
                "planning.standalone_wake.dispatched agent_id=%s",
                agent.id,
            )
        except (TimeoutError, asyncio.TimeoutError):
            self.logger.warning(
                "planning.standalone_wake.timeout agent_id=%s timeout_s=%s",
                agent.id,
                _STANDALONE_WAKE_TIMEOUT_SECONDS,
            )
        except Exception:
            self.logger.exception(
                "planning.standalone_wake.failed agent_id=%s",
                agent.id,
            )

    async def dispatch_plan_decompose(
        self,
        *,
        board: Board,
        plan: Plan,
        prompt: str,
        correlation_id: str | None = None,
    ) -> str:
        """Dispatch a decompose prompt honouring ``plan.decomposition_target``.

        When ``decomposition_target == "org_planner"`` and the configured org
        planner agent has an active gateway session, route to it. Otherwise
        fall back to the board lead session via :meth:`dispatch_plan_start`.
        """
        if plan.decomposition_target == "org_planner":
            resolved = await self._resolve_org_agent_session(settings.org_planner_agent_id)
            if resolved is not None:
                session_key, agent_name = resolved
                return await self._dispatch_to_session(
                    board=board,
                    session_key=session_key,
                    agent_name=agent_name,
                    prompt=prompt,
                    correlation_id=correlation_id,
                    log_prefix="planning.decompose",
                )
            self.logger.warning(
                "planning.decompose.org_planner_unavailable board_id=%s plan_id=%s "
                "falling back to board lead",
                board.id,
                plan.id,
            )
        return await self.dispatch_plan_start(
            board=board,
            prompt=prompt,
            correlation_id=correlation_id,
        )

    async def dispatch_to_configured_org_agent(
        self,
        *,
        board: Board,
        configured_agent_id: str,
        prompt: str,
        log_prefix: str,
        correlation_id: str | None = None,
    ) -> str | None:
        """Dispatch a one-shot message to an org-wide standalone agent.

        Returns the session_key used on success, or ``None`` when the
        configured agent is not available (caller decides whether to error).
        """
        resolved = await self._resolve_org_agent_session(configured_agent_id)
        if resolved is None:
            return None
        session_key, agent_name = resolved
        return await self._dispatch_to_session(
            board=board,
            session_key=session_key,
            agent_name=agent_name,
            prompt=prompt,
            correlation_id=correlation_id,
            log_prefix=log_prefix,
        )

    async def _dispatch_to_session(
        self,
        *,
        board: Board,
        session_key: str,
        agent_name: str,
        prompt: str,
        correlation_id: str | None,
        log_prefix: str,
    ) -> str:
        trace_id = GatewayDispatchService.resolve_trace_id(correlation_id, prefix=log_prefix)
        _gateway, config = await GatewayDispatchService(
            self.session,
        ).require_gateway_config_for_board(board)
        try:
            await self._dispatch_gateway_message(
                session_key=session_key,
                config=config,
                agent_name=agent_name,
                message=prompt,
                deliver=True,
            )
        except (OpenClawGatewayError, TimeoutError) as exc:
            self.logger.error(
                "gateway.%s.failed trace_id=%s board_id=%s session_key=%s error=%s",
                log_prefix,
                trace_id,
                board.id,
                session_key,
                str(exc),
            )
            raise map_gateway_error_to_http_exception(PLAN_DISPATCH_OPERATION, exc) from exc
        self.logger.info(
            "gateway.%s.success trace_id=%s board_id=%s session_key=%s",
            log_prefix,
            trace_id,
            board.id,
            session_key,
        )
        return session_key

    async def dispatch_plan_start(
        self,
        *,
        board: Board,
        prompt: str,
        correlation_id: str | None = None,
    ) -> str:
        """Send the opening prompt to the board lead agent's gateway session.

        Uses the board lead's existing session so the agent has proper board
        context, auth token, and memory.  Falls back to the gateway main
        session when no provisioned lead is found.
        """
        trace_id = GatewayDispatchService.resolve_trace_id(correlation_id, prefix="planning.start")
        self.logger.log(
            TRACE_LEVEL,
            "gateway.planning.start_dispatch.start trace_id=%s board_id=%s",
            trace_id,
            board.id,
        )
        gateway, config = await GatewayDispatchService(
            self.session
        ).require_gateway_config_for_board(board)

        # Prefer the board lead's session: it has the right X-Agent-Token and board context.
        lead = await Agent.objects.filter_by(board_id=board.id, is_board_lead=True).first(
            self.session
        )

        if lead is not None and lead.openclaw_session_id:
            session_key = lead.openclaw_session_id
            agent_name = lead.name
        else:
            # Fallback: gateway main session (no board-specific auth token).
            session_key = GatewayAgentIdentity.session_key(gateway)
            agent_name = "Gateway Agent"
            self.logger.warning(
                "gateway.planning.start_dispatch.no_lead trace_id=%s board_id=%s "
                "falling back to gateway main session",
                trace_id,
                board.id,
            )
        try:
            await self._dispatch_gateway_message(
                session_key=session_key,
                config=config,
                agent_name=agent_name,
                message=prompt,
                deliver=True,
            )
        except (OpenClawGatewayError, TimeoutError) as exc:
            self.logger.error(
                "gateway.planning.start_dispatch.failed trace_id=%s board_id=%s error=%s",
                trace_id,
                board.id,
                str(exc),
            )
            raise map_gateway_error_to_http_exception(PLAN_DISPATCH_OPERATION, exc) from exc
        self.logger.info(
            "gateway.planning.start_dispatch.success trace_id=%s board_id=%s session_key=%s",
            trace_id,
            board.id,
            session_key,
        )
        return session_key

    async def dispatch_plan_message(
        self,
        *,
        board: Board,
        plan: Plan,
        message: str,
        correlation_id: str | None = None,
    ) -> None:
        """Send a user message to the agent for an existing planning session."""
        trace_id = GatewayDispatchService.resolve_trace_id(
            correlation_id, prefix="planning.message"
        )
        self.logger.log(
            TRACE_LEVEL,
            "gateway.planning.message_dispatch.start trace_id=%s board_id=%s plan_id=%s",
            trace_id,
            board.id,
            plan.id,
        )
        _gateway, config = await GatewayDispatchService(
            self.session
        ).require_gateway_config_for_board(board)

        # Always route to the board lead's session for proper auth and board context.
        lead = await Agent.objects.filter_by(board_id=board.id, is_board_lead=True).first(
            self.session
        )

        if lead is not None and lead.openclaw_session_id:
            session_key = lead.openclaw_session_id
            agent_name = lead.name
        else:
            session_key = plan.session_key
            agent_name = "Gateway Agent"

        try:
            await self._dispatch_gateway_message(
                session_key=session_key,
                config=config,
                agent_name=agent_name,
                message=message,
                deliver=True,
            )
        except (OpenClawGatewayError, TimeoutError) as exc:
            self.logger.error(
                "gateway.planning.message_dispatch.failed trace_id=%s board_id=%s "
                "plan_id=%s error=%s",
                trace_id,
                board.id,
                plan.id,
                str(exc),
            )
            raise map_gateway_error_to_http_exception(PLAN_DISPATCH_OPERATION, exc) from exc
        self.logger.info(
            "gateway.planning.message_dispatch.success trace_id=%s board_id=%s plan_id=%s",
            trace_id,
            board.id,
            plan.id,
        )
