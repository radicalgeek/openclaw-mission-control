"""Pydantic schemas for thread message API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class ThreadMessageCreate(SQLModel):
    """Payload for posting a message to a thread."""

    content: str
    content_type: str = "text"


class ThreadMessageUpdate(SQLModel):
    """Payload for editing a message."""

    content: str


class ThreadMessageRead(SQLModel):
    """Thread message payload returned from read endpoints."""

    id: UUID
    thread_id: UUID
    sender_type: str
    sender_id: UUID | None
    sender_name: str
    content: str
    content_type: str
    event_metadata: dict[str, Any] | None
    is_edited: bool
    created_at: datetime
    updated_at: datetime
