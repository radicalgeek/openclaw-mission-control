"""Gateway messaging service for planning sessions."""

from __future__ import annotations

from app.core.logging import TRACE_LEVEL
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
        """Initialize a new gateway session for a planning document and send the opening prompt."""
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
        session_key = GatewayAgentIdentity.session_key(gateway)
        try:
            await self._dispatch_gateway_message(
                session_key=session_key,
                config=config,
                agent_name="Gateway Agent",
                message=prompt,
                deliver=False,
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
        try:
            await self._dispatch_gateway_message(
                session_key=plan.session_key,
                config=config,
                agent_name="Gateway Agent",
                message=message,
                deliver=False,
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
