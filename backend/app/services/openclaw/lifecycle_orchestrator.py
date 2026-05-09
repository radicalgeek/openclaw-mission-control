"""Unified agent lifecycle orchestration.

This module centralizes DB-backed lifecycle transitions so call sites do not
duplicate provisioning/wake/state logic.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import col, select

from app.core.agent_tokens import verify_agent_token
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.constants import (  # noqa: F401 (kept for import compat)
    CHECKIN_DEADLINE_AFTER_WAKE,
)
from app.services.openclaw.db_agent_state import (
    mark_provision_complete,
    mark_provision_requested,
    mint_agent_token,
)
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import openclaw_call
from app.services.openclaw.internal.agent_key import agent_key as _agent_key
from app.services.openclaw.lifecycle_queue import (
    QueuedAgentLifecycleReconcile,
    enqueue_lifecycle_reconcile,
)
from app.services.openclaw.provisioning import OpenClawGatewayProvisioner
from app.services.openclaw.shared import GatewayAgentIdentity
from app.services.organizations import get_org_owner_user

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.users import User


logger = get_logger(__name__)


def _agent_gateway_id(agent: Agent, gateway: Gateway, board: Board | None) -> str:
    if board is None and agent.agent_type != AGENT_TYPE_STANDALONE:
        return GatewayAgentIdentity.openclaw_agent_id(gateway)
    return _agent_key(agent)


def _extract_tools_auth_token(content: str) -> str | None:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator and key.strip() == "AUTH_TOKEN":
            token = value.strip()
            return token or None
    return None


def _agent_file_content(payload: object) -> str | None:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return None
    content = payload.get("content")
    if isinstance(content, str):
        return content
    file_obj = payload.get("file")
    if isinstance(file_obj, dict):
        nested = file_obj.get("content")
        if isinstance(nested, str):
            return nested
    return None


async def _read_workspace_auth_token(
    *,
    gateway: Gateway,
    agent: Agent,
    board: Board | None,
) -> str | None:
    if not gateway.url:
        return None
    config = GatewayClientConfig(
        url=gateway.url,
        token=gateway.token,
        allow_insecure_tls=gateway.allow_insecure_tls,
        disable_device_pairing=gateway.disable_device_pairing,
    )
    try:
        payload = await openclaw_call(
            "agents.files.get",
            {"agentId": _agent_gateway_id(agent, gateway, board), "name": "TOOLS.md"},
            config=config,
        )
    except (OpenClawGatewayError, TimeoutError) as exc:
        logger.warning(
            "lifecycle.workspace_token.read_failed",
            extra={"agent_id": str(agent.id), "error": str(exc)},
        )
        return None
    content = _agent_file_content(payload)
    if not content:
        return None
    return _extract_tools_auth_token(content)


async def _resolve_update_auth_token(
    *,
    gateway: Gateway,
    agent: Agent,
    board: Board | None,
) -> str | None:
    """Resolve a raw token for an update without causing token churn.

    Existing update flows usually only have the hashed DB token, so they used
    to skip template writes entirely. That preserves a valid workspace, but it
    also means a stale TOOLS.md token can never self-heal. Reading TOOLS.md lets
    us distinguish "valid current token" from "stale token" and only rotate
    when the workspace is already broken.
    """

    workspace_token = await _read_workspace_auth_token(
        gateway=gateway,
        agent=agent,
        board=board,
    )
    if not workspace_token:
        return None
    if agent.agent_token_hash and verify_agent_token(workspace_token, agent.agent_token_hash):
        return workspace_token
    logger.warning(
        "lifecycle.workspace_token.mismatch_rotating",
        extra={"agent_id": str(agent.id)},
    )
    return mint_agent_token(agent)


class AgentLifecycleOrchestrator(OpenClawDBService):
    """Single lifecycle writer for agent provision/update transitions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _lock_agent(self, *, agent_id: UUID) -> Agent:
        statement = select(Agent).where(col(Agent.id) == agent_id).with_for_update()
        agent = (await self.session.exec(statement)).first()
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        return agent

    async def run_lifecycle(
        self,
        *,
        gateway: Gateway,
        agent_id: UUID,
        board: Board | None,
        user: User | None,
        action: str,
        auth_token: str | None = None,
        force_bootstrap: bool = False,
        reset_session: bool = False,
        wake: bool = True,
        deliver_wakeup: bool = True,
        wakeup_verb: str | None = None,
        clear_confirm_token: bool = False,
        raise_gateway_errors: bool = True,
        extra_files: dict[str, str] | None = None,
        db_templates: dict[str, str] | None = None,
        patch_heartbeat: bool = True,
    ) -> Agent:
        """Provision or update any agent under a per-agent lock."""

        logger.info(
            "lifecycle.run_lifecycle.start",
            extra={
                "agent_id": str(agent_id),
                "action": action,
                "wake": wake,
                "reset_session": reset_session,
                "force_bootstrap": force_bootstrap,
                "board_id": str(board.id) if board is not None else None,
                "gateway_id": str(gateway.id),
                "auth_token_provided": auth_token is not None,
            },
        )

        locked = await self._lock_agent(agent_id=agent_id)
        # NOTE: `name` is a reserved attribute on Python's LogRecord — passing
        # it via `extra={...}` raises KeyError("Attempt to overwrite 'name' …").
        # Use `agent_name` here. Same hazard for `msg`, `args`, `levelname`,
        # `pathname`, `filename`, `module`, `lineno`, `funcName`, `created`,
        # `process`, `processName`, `thread`, `threadName`, `message`, `asctime`.
        logger.info(
            "lifecycle.run_lifecycle.locked",
            extra={
                "agent_id": str(locked.id),
                "agent_name": locked.name,
                "current_status": locked.status,
                "current_generation": locked.lifecycle_generation,
                "agent_token_hash_set": locked.agent_token_hash is not None,
                "openclaw_session_id": locked.openclaw_session_id,
                "last_seen_at": locked.last_seen_at.isoformat() if locked.last_seen_at else None,
                "wake_attempts": locked.wake_attempts,
            },
        )
        template_user = user
        if board is None and template_user is None:
            template_user = await get_org_owner_user(
                self.session,
                organization_id=gateway.organization_id,
            )
            if template_user is None:
                logger.warning(
                    "lifecycle.run_lifecycle.exit_no_org_owner",
                    extra={"agent_id": str(locked.id)},
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        "Organization owner not found "
                        "(required for gateway agent USER.md rendering)."
                    ),
                )

        # Only mint a new agent token when we genuinely need one. For updates,
        # try to recover the current raw token from TOOLS.md first: if it still
        # matches the DB hash we can safely refresh workspace files; if it does
        # not match, the agent is already broken with 401s, so rotate once and
        # rewrite the workspace before waking it.
        if auth_token:
            raw_token = auth_token
        elif action == "provision" or locked.agent_token_hash is None:
            raw_token = mint_agent_token(locked)
        else:
            raw_token = await _resolve_update_auth_token(
                gateway=gateway,
                agent=locked,
                board=board,
            )
        mark_provision_requested(
            locked,
            action=action,
            status="updating" if action == "update" else "provisioning",
        )
        locked.lifecycle_generation += 1
        locked.last_provision_error = None
        locked.checkin_deadline_at = (
            utcnow() + timedelta(seconds=settings.agent_checkin_deadline_seconds) if wake else None
        )
        if wake:
            locked.wake_attempts += 1
            locked.last_wake_sent_at = utcnow()
        self.session.add(locked)
        await self.session.flush()
        logger.info(
            "lifecycle.run_lifecycle.state_flushed",
            extra={
                "agent_id": str(locked.id),
                "new_generation": locked.lifecycle_generation,
                "raw_token_minted": raw_token is not None,
                "wake_attempts": locked.wake_attempts,
            },
        )

        if not gateway.url:
            logger.warning(
                "lifecycle.run_lifecycle.exit_no_gateway_url",
                extra={"agent_id": str(locked.id), "gateway_id": str(gateway.id)},
            )
            await self.session.commit()
            await self.session.refresh(locked)
            return locked

        logger.info(
            "lifecycle.run_lifecycle.apply_start",
            extra={
                "agent_id": str(locked.id),
                "gateway_url": gateway.url,
                "raw_token_provided": raw_token is not None,
            },
        )
        try:
            await OpenClawGatewayProvisioner().apply_agent_lifecycle(
                agent=locked,
                gateway=gateway,
                board=board,
                auth_token=raw_token,
                user=template_user,
                action=action,
                force_bootstrap=force_bootstrap,
                reset_session=reset_session,
                wake=wake,
                deliver_wakeup=deliver_wakeup,
                wakeup_verb=wakeup_verb,
                extra_files=extra_files,
                db_templates=db_templates,
                patch_heartbeat=patch_heartbeat,
            )
        except OpenClawGatewayError as exc:
            logger.warning(
                "lifecycle.run_lifecycle.apply_gateway_error",
                extra={"agent_id": str(locked.id), "error": str(exc)},
            )
            locked.last_provision_error = str(exc)
            locked.updated_at = utcnow()
            self.session.add(locked)
            await self.session.commit()
            await self.session.refresh(locked)
            if wake and locked.checkin_deadline_at is not None:
                enqueue_lifecycle_reconcile(
                    QueuedAgentLifecycleReconcile(
                        agent_id=locked.id,
                        gateway_id=locked.gateway_id,
                        board_id=locked.board_id,
                        generation=locked.lifecycle_generation,
                        checkin_deadline_at=locked.checkin_deadline_at,
                    )
                )
            if raise_gateway_errors:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gateway {action} failed: {exc}",
                ) from exc
            return locked
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning(
                "lifecycle.run_lifecycle.apply_local_error",
                extra={
                    "agent_id": str(locked.id),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            locked.last_provision_error = str(exc)
            locked.updated_at = utcnow()
            self.session.add(locked)
            await self.session.commit()
            await self.session.refresh(locked)
            if wake and locked.checkin_deadline_at is not None:
                enqueue_lifecycle_reconcile(
                    QueuedAgentLifecycleReconcile(
                        agent_id=locked.id,
                        gateway_id=locked.gateway_id,
                        board_id=locked.board_id,
                        generation=locked.lifecycle_generation,
                        checkin_deadline_at=locked.checkin_deadline_at,
                    )
                )
            if raise_gateway_errors:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Unexpected error {action}ing gateway provisioning.",
                ) from exc
            return locked

        logger.info(
            "lifecycle.run_lifecycle.apply_done",
            extra={"agent_id": str(locked.id)},
        )
        mark_provision_complete(
            locked,
            status="online",
            clear_confirm_token=clear_confirm_token,
        )
        locked.last_provision_error = None
        locked.checkin_deadline_at = (
            utcnow() + timedelta(seconds=settings.agent_checkin_deadline_seconds) if wake else None
        )
        self.session.add(locked)
        await self.session.commit()
        await self.session.refresh(locked)
        if wake and locked.checkin_deadline_at is not None:
            enqueue_lifecycle_reconcile(
                QueuedAgentLifecycleReconcile(
                    agent_id=locked.id,
                    gateway_id=locked.gateway_id,
                    board_id=locked.board_id,
                    generation=locked.lifecycle_generation,
                    checkin_deadline_at=locked.checkin_deadline_at,
                )
            )
        logger.info(
            "lifecycle.run_lifecycle.complete",
            extra={
                "agent_id": str(locked.id),
                "final_status": locked.status,
                "generation": locked.lifecycle_generation,
            },
        )
        return locked
