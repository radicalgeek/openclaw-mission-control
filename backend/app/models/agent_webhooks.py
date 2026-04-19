"""Agent webhook configuration and payload models for standalone agents."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class AgentWebhook(QueryModel, table=True):
    """Inbound webhook endpoint configuration scoped to an agent."""

    __tablename__ = "agent_webhooks"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agents.id", index=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    description: str
    enabled: bool = Field(default=True, index=True)
    secret: str | None = Field(default=None)
    signature_header: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AgentWebhookPayload(QueryModel, table=True):
    """Captured inbound payload received on an agent webhook."""

    __tablename__ = "agent_webhook_payloads"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agents.id", index=True)
    webhook_id: UUID = Field(foreign_key="agent_webhooks.id", index=True)
    payload: dict[str, object] | list[object] | str | int | float | bool | None = Field(
        default=None,
        sa_column=Column(JSON),
    )
    headers: dict[str, str] | None = Field(default=None, sa_column=Column(JSON))
    source_ip: str | None = None
    content_type: str | None = None
    received_at: datetime = Field(default_factory=utcnow, index=True)
