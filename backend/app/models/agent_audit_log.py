"""Agent audit log model — append-only structured audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Numeric, Text
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)

AUDIT_SOURCE_PRODUCT_FOUNDRY = "product_foundry"
AUDIT_SOURCE_GATEWAY_RPC = "gateway_rpc"
AUDIT_SOURCE_COMMAND_LOGGER = "command_logger"
AUDIT_SOURCE_WEBHOOK = "webhook"
AUDIT_SOURCE_AGENT_SELF_REPORT = "agent_self_report"

AUDIT_ACTOR_AGENT = "agent"
AUDIT_ACTOR_USER = "user"
AUDIT_ACTOR_SYSTEM = "system"

AUDIT_CATEGORY_LIFECYCLE = "lifecycle"
AUDIT_CATEGORY_COMMAND = "command"
AUDIT_CATEGORY_CHAT = "chat"
AUDIT_CATEGORY_APPROVAL = "approval"
AUDIT_CATEGORY_COST = "cost"
AUDIT_CATEGORY_CONFIG = "config"
AUDIT_CATEGORY_CHANNEL = "channel"
AUDIT_CATEGORY_SPRINT = "sprint"
AUDIT_CATEGORY_PLANNING = "planning"
AUDIT_CATEGORY_SKILL = "skill"
AUDIT_CATEGORY_MCP = "mcp"
AUDIT_CATEGORY_FILE = "file"
AUDIT_CATEGORY_GOVERNANCE = "governance"


class AgentAuditLog(QueryModel, table=True):
    """Append-only audit trail for agent actions."""

    __tablename__ = "agent_audit_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    gateway_id: UUID | None = Field(default=None, foreign_key="gateways.id", index=True)
    board_id: UUID | None = Field(default=None, foreign_key="boards.id", index=True)
    agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    task_id: UUID | None = Field(default=None, foreign_key="tasks.id")
    session_key: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    thread_id: UUID | None = Field(default=None, foreign_key="threads.id")
    sprint_id: UUID | None = Field(default=None, foreign_key="sprints.id")
    event_category: str = Field(index=True)
    event_action: str = Field(index=True)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    token_input: int | None = Field(default=None)
    token_output: int | None = Field(default=None)
    cost_usd: float | None = Field(default=None, sa_column=Column(Numeric(12, 6), nullable=True))
    model_id: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    correlation_id: str | None = Field(default=None, index=True)
    source: str = Field(default=AUDIT_SOURCE_PRODUCT_FOUNDRY, index=True)
    actor_type: str = Field(default=AUDIT_ACTOR_SYSTEM)
    actor_id: UUID | None = Field(default=None)
    ip_address: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, index=True)
