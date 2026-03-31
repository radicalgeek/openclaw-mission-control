"""Gateway messaging service for planning sessions."""

from __future__ import annotations

from app.core.logging import TRACE_LEVEL
from app.models.agents import Agent
from app.models.boards import Board
from app.models.plans import Plan
from app.services.openclaw.coordination_service import AbstractGatewayMessagingService
from app.services.openclaw.exceptions import GatewayOperation, map_gateway_error_to_http_exception
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.shared import GatewayAgentIdentity

PLAN_DISPATCH_OPERATION = GatewayOperation.LEAD_MESSAGE_DISPATCH


class PlanningMessagingService(AbstractGatewayMessagingService):
    """Gateway message dispatch helpers for planning session routes."""

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
        trace_id = GatewayDispatchService.resolve_trace_id(
            correlation_id, prefix="planning.start"
        )
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
        lead = await Agent.objects.filter_by(
            board_id=board.id, is_board_lead=True
        ).first(self.session)

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
        lead = await Agent.objects.filter_by(
            board_id=board.id, is_board_lead=True
        ).first(self.session)

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
