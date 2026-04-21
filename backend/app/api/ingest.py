"""Ingest endpoints for command-logger output and agent self-reported usage."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, status

from app.api.deps import IngestCallerContext, require_ingest_caller
from app.core.time import utcnow
from app.db.session import get_session
from app.models.agent_audit_log import (
    AUDIT_ACTOR_AGENT,
    AUDIT_ACTOR_SYSTEM,
    AUDIT_CATEGORY_COMMAND,
    AUDIT_SOURCE_COMMAND_LOGGER,
    AgentAuditLog,
)
from app.models.usage_snapshots import SNAPSHOT_TYPE_AGENT_REPORT, UsageSnapshot
from app.schemas.audit import CommandIngestRequest, UsageIngestRequest
from app.schemas.common import OkResponse

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(tags=["agent-ingest"])

SESSION_DEP = Depends(get_session)
INGEST_CALLER_DEP = Depends(require_ingest_caller)

_RUNTIME_TYPE_REFERENCES = (UUID, datetime)


@router.post(
    "/agent/ingest/commands",
    response_model=OkResponse,
    status_code=status.HTTP_200_OK,
    tags=["agent-ingest"],
    summary="Ingest command-logger events",
    description=(
        "Accepts structured command audit logs from an OpenClaw pod sidecar. "
        "Each item is stored as an audit row with source='command_logger'."
    ),
)
@router.post(
    "/ingest/commands",
    response_model=OkResponse,
    status_code=status.HTTP_200_OK,
    tags=["agent-ingest"],
    include_in_schema=False,
)
async def ingest_commands(
    payload: CommandIngestRequest,
    session: "AsyncSession" = SESSION_DEP,
    caller: IngestCallerContext = INGEST_CALLER_DEP,
) -> OkResponse:
    """Ingest command-logger output from a pod sidecar or hook."""
    now = utcnow()
    # When called by an authenticated agent, use its identity as the actor.
    # When called by a human operator, fall back to per-item agent_id.
    caller_is_agent = caller.agent_id is not None
    for item in payload.commands:
        resolved_agent_id = caller.agent_id if caller_is_agent else item.agent_id
        audit = AgentAuditLog(
            id=uuid4(),
            organization_id=caller.organization_id,
            gateway_id=caller.gateway_id,
            agent_id=resolved_agent_id,
            session_key=item.session_key,
            event_category=AUDIT_CATEGORY_COMMAND,
            event_action=f"command.{item.tool_name}",
            detail={
                "tool_name": item.tool_name,
                "args": item.args,
                "result": item.result,
            },
            token_input=item.token_input,
            token_output=item.token_output,
            cost_usd=item.cost_usd,
            model_id=item.model_id,
            correlation_id=item.correlation_id,
            source=AUDIT_SOURCE_COMMAND_LOGGER,
            actor_type=AUDIT_ACTOR_AGENT if caller_is_agent else AUDIT_ACTOR_SYSTEM,
            actor_id=resolved_agent_id,
            created_at=item.occurred_at or now,
        )
        session.add(audit)
    await session.commit()
    return OkResponse(ok=True)


@router.post(
    "/agent/ingest/usage",
    response_model=OkResponse,
    status_code=status.HTTP_200_OK,
    tags=["agent-ingest"],
    summary="Ingest agent self-reported usage",
    description=(
        "Accepts token/cost telemetry self-reported by an agent. Stored as "
        "usage snapshots with snapshot_type='agent_report'."
    ),
)
@router.post(
    "/ingest/usage",
    response_model=OkResponse,
    status_code=status.HTTP_200_OK,
    tags=["agent-ingest"],
    include_in_schema=False,
)
async def ingest_usage(
    payload: UsageIngestRequest,
    session: "AsyncSession" = SESSION_DEP,
    caller: IngestCallerContext = INGEST_CALLER_DEP,
) -> OkResponse:
    """Ingest agent self-reported token/cost data."""
    if caller.gateway_id is None:
        # Human operator submission: gateway required for FK integrity.
        # Silently no-op if no gateway can be resolved (data would be unattributed).
        # Future: accept gateway_id in request body from operators.
        return OkResponse(ok=True)
    now = utcnow()
    for item in payload.items:
        snap = UsageSnapshot(
            id=uuid4(),
            organization_id=caller.organization_id,
            gateway_id=caller.gateway_id,
            agent_id=caller.agent_id,
            session_key=item.session_key,
            model_id=item.model_id,
            prompt_tokens=item.token_input,
            completion_tokens=item.token_output,
            total_tokens=item.token_input + item.token_output,
            cost_usd=item.cost_usd,
            snapshot_type=SNAPSHOT_TYPE_AGENT_REPORT,
            captured_at=item.occurred_at or now,
        )
        session.add(snap)
    await session.commit()
    return OkResponse(ok=True)
