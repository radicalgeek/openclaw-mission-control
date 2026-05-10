"""DB-backed gateway config resolution and message dispatch helpers.

This module exists to keep `app.api.*` thin: APIs should call OpenClaw services, not
directly orchestrate gateway RPC calls.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_resolver import (
    gateway_client_config,
    get_gateway_for_board,
    optional_gateway_client_config,
    require_gateway_for_board,
)
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import (
    OpenClawGatewayError,
    ensure_session,
    openclaw_call,
    send_message,
    send_session_message_nonblocking,
)

_RESETTABLE_SESSION_STATES = frozenset({"failed", "processing"})


def _session_item_key(item: dict[str, object]) -> str:
    for field in ("key", "sessionKey", "session_key"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _session_items(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        maybe_items = payload.get("sessions") or payload.get("items") or []
        if isinstance(maybe_items, list):
            return [item for item in maybe_items if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


async def reset_stuck_session_if_needed(
    *,
    session_key: str,
    config: GatewayClientConfig,
) -> bool:
    """Reset failed/processing sessions before sending a recovery wake."""
    try:
        sessions = await openclaw_call("sessions.list", {}, config=config)
    except Exception:
        return False

    for item in _session_items(sessions):
        if _session_item_key(item) != session_key:
            continue
        raw_state = item.get("state") or item.get("status")
        state = str(raw_state or "").lower()
        if state not in _RESETTABLE_SESSION_STATES:
            return False
        try:
            await openclaw_call("sessions.reset", {"key": session_key}, config=config)
        except Exception:
            return False
        return True
    return False


async def reset_session_best_effort(
    *,
    session_key: str,
    config: GatewayClientConfig,
) -> bool:
    """Reset a session without failing the caller when the gateway refuses it."""
    try:
        await openclaw_call("sessions.reset", {"key": session_key}, config=config)
    except Exception:
        return False
    return True


class GatewayDispatchService(OpenClawDBService):
    """Resolve gateway config for boards and dispatch messages to agent sessions."""

    async def optional_gateway_config_for_board(
        self,
        board: Board,
    ) -> GatewayClientConfig | None:
        gateway = await get_gateway_for_board(self.session, board)
        return optional_gateway_client_config(gateway)

    async def optional_gateway_config_for_agent(
        self,
        agent: Agent,
    ) -> GatewayClientConfig | None:
        """Resolve gateway config directly from the agent's gateway_id (for standalone agents)."""
        gateway = await Gateway.objects.by_id(agent.gateway_id).first(self.session)
        return optional_gateway_client_config(gateway)

    async def require_gateway_config_for_board(
        self,
        board: Board,
    ) -> tuple[Gateway, GatewayClientConfig]:
        gateway = await require_gateway_for_board(self.session, board)
        return gateway, gateway_client_config(gateway)

    async def send_agent_message(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> None:
        await ensure_session(session_key, config=config, label=agent_name)
        await send_message(message, session_key=session_key, config=config, deliver=deliver)

    async def wake_agent_session(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
        agent_name: str,
        message: str,
        model: str | None = None,
        clear_model_override: bool = False,
        reset_stuck_session: bool = False,
    ) -> None:
        """Start an agent turn without blocking the API request on completion."""
        if reset_stuck_session:
            reset = await reset_stuck_session_if_needed(
                session_key=session_key,
                config=config,
            )
            if not reset:
                await reset_session_best_effort(
                    session_key=session_key,
                    config=config,
                )
        await ensure_session(
            session_key,
            config=config,
            label=agent_name,
            model=model,
            clear_model_override=clear_model_override,
        )
        await send_session_message_nonblocking(
            message,
            session_key=session_key,
            config=config,
        )

    async def try_send_agent_message(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> OpenClawGatewayError | None:
        try:
            await self.send_agent_message(
                session_key=session_key,
                config=config,
                agent_name=agent_name,
                message=message,
                deliver=deliver,
            )
        except OpenClawGatewayError as exc:
            return exc
        return None

    async def try_wake_agent_session(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
        agent_name: str,
        message: str,
        model: str | None = None,
        clear_model_override: bool = False,
        reset_stuck_session: bool = False,
    ) -> OpenClawGatewayError | None:
        try:
            await self.wake_agent_session(
                session_key=session_key,
                config=config,
                agent_name=agent_name,
                message=message,
                model=model,
                clear_model_override=clear_model_override,
                reset_stuck_session=reset_stuck_session,
            )
        except OpenClawGatewayError as exc:
            return exc
        return None

    @staticmethod
    def resolve_trace_id(correlation_id: str | None, *, prefix: str) -> str:
        normalized = (correlation_id or "").strip()
        if normalized:
            return normalized
        return f"{prefix}:{uuid4().hex[:12]}"
