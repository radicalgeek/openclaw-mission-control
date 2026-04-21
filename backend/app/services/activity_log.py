"""Utilities for recording normalized activity events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.agent_audit_log import (
    AUDIT_ACTOR_SYSTEM,
    AUDIT_SOURCE_PRODUCT_FOUNDRY,
    AgentAuditLog,
)

# Mapping from activity event_type prefix → audit category
_CATEGORY_MAP: dict[str, str] = {
    "agent.file.": "file",
    "agent.": "lifecycle",
    "task.": "lifecycle",
    "sprint.": "sprint",
    "plan.": "planning",
    "approval.": "approval",
    "channel.": "channel",
    "thread.": "channel",
    "skill.": "skill",
    "mcp.": "mcp",
    "board.": "governance",
}


def _infer_category(event_type: str) -> str:
    for prefix, category in _CATEGORY_MAP.items():
        if event_type.startswith(prefix):
            return category
    return "lifecycle"


def record_activity(
    session: "AsyncSession",
    *,
    event_type: str,
    message: str,
    agent_id: "UUID | None" = None,
    task_id: "UUID | None" = None,
    board_id: "UUID | None" = None,
    # Extended fields for dual-write to agent_audit_log
    organization_id: "UUID | None" = None,
    gateway_id: "UUID | None" = None,
    thread_id: "UUID | None" = None,
    sprint_id: "UUID | None" = None,
    session_key: str | None = None,
    actor_type: str = AUDIT_ACTOR_SYSTEM,
    actor_id: "UUID | None" = None,
    detail: "dict[str, Any] | None" = None,
    token_input: int | None = None,
    token_output: int | None = None,
    cost_usd: float | None = None,
    model_id: str | None = None,
    correlation_id: str | None = None,
    ip_address: str | None = None,
) -> ActivityEvent:
    """Create and attach an activity event row to the current DB session.

    When ``organization_id`` is provided, also dual-writes to ``agent_audit_log``
    for structured audit coverage.
    """
    event = ActivityEvent(
        event_type=event_type,
        message=message,
        agent_id=agent_id,
        task_id=task_id,
        board_id=board_id,
    )
    session.add(event)

    if organization_id is not None:
        audit = AgentAuditLog(
            organization_id=organization_id,
            gateway_id=gateway_id,
            board_id=board_id,
            agent_id=agent_id,
            task_id=task_id,
            session_key=session_key,
            thread_id=thread_id,
            sprint_id=sprint_id,
            event_category=_infer_category(event_type),
            event_action=event_type,
            detail=detail or {"message": message},
            token_input=token_input,
            token_output=token_output,
            cost_usd=cost_usd,
            model_id=model_id,
            correlation_id=correlation_id,
            source=AUDIT_SOURCE_PRODUCT_FOUNDRY,
            actor_type=actor_type,
            actor_id=actor_id,
            ip_address=ip_address,
            created_at=utcnow(),
        )
        session.add(audit)

    return event


def record_audit(
    session: "AsyncSession",
    *,
    organization_id: "UUID",
    event_category: str,
    event_action: str,
    gateway_id: "UUID | None" = None,
    board_id: "UUID | None" = None,
    agent_id: "UUID | None" = None,
    task_id: "UUID | None" = None,
    session_key: str | None = None,
    thread_id: "UUID | None" = None,
    sprint_id: "UUID | None" = None,
    detail: "dict[str, Any] | None" = None,
    token_input: int | None = None,
    token_output: int | None = None,
    cost_usd: float | None = None,
    model_id: str | None = None,
    correlation_id: str | None = None,
    source: str = AUDIT_SOURCE_PRODUCT_FOUNDRY,
    actor_type: str = AUDIT_ACTOR_SYSTEM,
    actor_id: "UUID | None" = None,
    ip_address: str | None = None,
) -> AgentAuditLog:
    """Write directly to agent_audit_log without creating an ActivityEvent.

    Use for events that need audit coverage but no legacy activity log entry
    (e.g. gateway RPC snapshots, command-logger ingestion).
    """
    audit = AgentAuditLog(
        organization_id=organization_id,
        gateway_id=gateway_id,
        board_id=board_id,
        agent_id=agent_id,
        task_id=task_id,
        session_key=session_key,
        thread_id=thread_id,
        sprint_id=sprint_id,
        event_category=event_category,
        event_action=event_action,
        detail=detail,
        token_input=token_input,
        token_output=token_output,
        cost_usd=cost_usd,
        model_id=model_id,
        correlation_id=correlation_id,
        source=source,
        actor_type=actor_type,
        actor_id=actor_id,
        ip_address=ip_address,
        created_at=utcnow(),
    )
    session.add(audit)
    return audit
