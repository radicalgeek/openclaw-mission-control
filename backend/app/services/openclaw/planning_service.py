"""Gateway messaging service for planning sessions."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import col, select

from app.core.config import settings
from app.core.logging import TRACE_LEVEL
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.plans import Plan
from app.services.openclaw.coordination_service import AbstractGatewayMessagingService
from app.services.openclaw.exceptions import GatewayOperation, map_gateway_error_to_http_exception
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.openclaw.shared import GatewayAgentIdentity

PLAN_DISPATCH_OPERATION = GatewayOperation.LEAD_MESSAGE_DISPATCH

# Substring used to detect "agent not registered in gateway config" — the gateway
# returns this when a session_key references an agent that has been dropped from
# the running config (typical after a worker restart). When we see it, we
# re-register the agent (agents.create, no bootstrap) and retry once.
_AGENT_MISSING_HINT = "no longer exists in configuration"


class PlanningMessagingService(AbstractGatewayMessagingService):
    """Gateway message dispatch helpers for planning session routes."""

    async def _resolve_org_agent(
        self,
        agent_id_setting: str | None,
        *,
        gateway_id: UUID | None = None,
        role_template: str | None = None,
    ) -> Agent | None:
        """Look up an org-wide standalone agent.

        Prefer a live role-template lookup scoped to the board's gateway so
        recreated standalone agents are picked up without env var changes.
        ``agent_id_setting`` remains as a compatibility fallback for older
        deployments and tests.
        """
        if gateway_id is not None and role_template:
            agents = (
                await self.session.exec(
                    select(Agent)
                    .where(col(Agent.gateway_id) == gateway_id)
                    .where(col(Agent.agent_type) == AGENT_TYPE_STANDALONE)
                    .order_by(col(Agent.updated_at).desc())
                )
            ).all()
            for agent in agents:
                profile = agent.identity_profile if isinstance(agent.identity_profile, dict) else {}
                if profile.get("role_template") == role_template and agent.openclaw_session_id:
                    return agent

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
        return agent

    async def _wake_standalone_agent(
        self,
        *,
        agent: Agent,
        gateway: Gateway,
        log_prefix: str,
        trace_id: str,
    ) -> None:
        """Re-register a standalone agent in the gateway's running config.

        Runs ``run_lifecycle(action="update")`` with no bootstrap and no
        wake-up message — just enough to put the agent back in
        ``agents.list`` so a follow-up ``chat.send`` is accepted. The actual
        prompt is delivered by the caller right after this returns.
        """
        self.logger.info(
            "gateway.%s.relifecycle trace_id=%s agent_id=%s session_key=%s",
            log_prefix,
            trace_id,
            agent.id,
            agent.openclaw_session_id,
        )
        await AgentLifecycleOrchestrator(self.session).run_lifecycle(
            gateway=gateway,
            agent_id=agent.id,
            board=None,
            user=None,
            action="update",
            force_bootstrap=False,
            reset_session=False,
            wake=True,
            deliver_wakeup=False,
            clear_confirm_token=False,
            raise_gateway_errors=False,
            extra_files=None,
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

        Routes to the configured standalone agent matching the target
        (``org_triager`` or ``org_planner``). Falls back to the board lead
        session when the configured standalone is unavailable, or when the
        target is ``board_lead``. Note: per the agent role templates,
        decomposition is the **triager's** job; the planner does sprint
        composition. New plans should target ``org_triager``.
        """
        org_target_setting = {
            "org_triager": settings.org_triager_agent_id,
            "org_planner": settings.org_planner_agent_id,
        }.get(plan.decomposition_target)
        org_target_role = {
            "org_triager": "triager",
            "org_planner": "planner",
        }.get(plan.decomposition_target)

        if org_target_role is not None:
            agent = await self._resolve_org_agent(
                org_target_setting or "",
                gateway_id=board.gateway_id,
                role_template=org_target_role,
            )
            if agent is not None and agent.openclaw_session_id is not None:
                return await self._dispatch_to_session(
                    board=board,
                    session_key=agent.openclaw_session_id,
                    agent_name=agent.name,
                    prompt=prompt,
                    correlation_id=correlation_id,
                    log_prefix="planning.decompose",
                    standalone_agent=agent,
                )
            self.logger.warning(
                "planning.decompose.org_agent_unavailable target=%s board_id=%s "
                "plan_id=%s falling back to board lead",
                plan.decomposition_target,
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
        configured_agent_id: str | None,
        role_template: str | None = None,
        prompt: str,
        log_prefix: str,
        correlation_id: str | None = None,
    ) -> str | None:
        """Dispatch a one-shot message to an org-wide standalone agent.

        Returns the session_key used on success, or ``None`` when the
        configured agent is not available (caller decides whether to error).
        """
        agent = await self._resolve_org_agent(
            configured_agent_id,
            gateway_id=board.gateway_id,
            role_template=role_template,
        )
        if agent is None or agent.openclaw_session_id is None:
            return None
        return await self._dispatch_to_session(
            board=board,
            session_key=agent.openclaw_session_id,
            agent_name=agent.name,
            prompt=prompt,
            correlation_id=correlation_id,
            log_prefix=log_prefix,
            standalone_agent=agent,
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
        standalone_agent: Agent | None = None,
    ) -> str:
        trace_id = GatewayDispatchService.resolve_trace_id(correlation_id, prefix=log_prefix)
        gateway, config = await GatewayDispatchService(
            self.session,
        ).require_gateway_config_for_board(board)

        async def _send() -> None:
            await self._dispatch_gateway_message(
                session_key=session_key,
                config=config,
                agent_name=agent_name,
                message=prompt,
                deliver=True,
            )

        try:
            await _send()
        except OpenClawGatewayError as exc:
            # Lazy re-registration: if the gateway has dropped this agent from
            # its running config (typical after a worker restart), run an
            # ``agents.create`` lifecycle (no bootstrap, no wake-up message)
            # and retry once. Only attempted for standalone agents that we
            # have full lifecycle context for.
            if standalone_agent is not None and _AGENT_MISSING_HINT in str(exc):
                self.logger.warning(
                    "gateway.%s.agent_missing_in_config trace_id=%s session_key=%s "
                    "re-registering and retrying",
                    log_prefix,
                    trace_id,
                    session_key,
                )
                await self._wake_standalone_agent(
                    agent=standalone_agent,
                    gateway=gateway,
                    log_prefix=log_prefix,
                    trace_id=trace_id,
                )
                try:
                    await _send()
                except (OpenClawGatewayError, TimeoutError) as retry_exc:
                    self.logger.error(
                        "gateway.%s.failed trace_id=%s board_id=%s session_key=%s "
                        "error=%s (after re-register)",
                        log_prefix,
                        trace_id,
                        board.id,
                        session_key,
                        str(retry_exc),
                    )
                    raise map_gateway_error_to_http_exception(
                        PLAN_DISPATCH_OPERATION, retry_exc
                    ) from retry_exc
            else:
                self.logger.error(
                    "gateway.%s.failed trace_id=%s board_id=%s session_key=%s error=%s",
                    log_prefix,
                    trace_id,
                    board.id,
                    session_key,
                    str(exc),
                )
                raise map_gateway_error_to_http_exception(PLAN_DISPATCH_OPERATION, exc) from exc
        except TimeoutError as exc:
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
