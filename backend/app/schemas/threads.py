"""Pydantic schemas for thread API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class ThreadCreate(SQLModel):
    """Payload for creating a new thread in a channel."""

    topic: str
    content: str  # First message content


class ThreadUpdate(SQLModel):
    """Payload for updating a thread."""

    topic: str | None = None
    is_resolved: bool | None = None
    is_pinned: bool | None = None


class ThreadLinkTask(SQLModel):
    """Payload for linking a thread to an existing board task."""

    task_id: UUID


class ThreadRead(SQLModel):
    """Thread payload returned from read endpoints."""

    id: UUID
    channel_id: UUID
    topic: str
    task_id: UUID | None
    source_type: str
    source_ref: str | None
    is_resolved: bool
    is_pinned: bool
    message_count: int
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Computed fields (may be None if not loaded)
    last_message_preview: str | None = None
