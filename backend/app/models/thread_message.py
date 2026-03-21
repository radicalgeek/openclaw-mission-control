"""ThreadMessage model for individual messages within a thread."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class ThreadMessage(TenantScoped, table=True):
    """A message posted in a channel thread."""

    __tablename__ = "thread_messages"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    thread_id: UUID = Field(foreign_key="threads.id", index=True)
    sender_type: str = Field(default="user", index=True)  # "user", "agent", "webhook", "system"
    sender_id: UUID | None = Field(default=None, index=True)  # FK to User or Agent (nullable)
    sender_name: str = Field(default="")
    content: str = Field(default="")
    content_type: str = Field(
        default="text"
    )  # "text", "webhook_event", "agent_response", "system_notification"
    event_metadata: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column("metadata", JSON),
    )
    is_edited: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
