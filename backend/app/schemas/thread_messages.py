"""Pydantic schemas for thread message API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class ThreadMessageCreate(SQLModel):
    """Payload for posting a message to a thread.

    Supported ``content_type`` values:
    - ``"text"`` — plain text / Markdown (default)
    - ``"webhook_event"`` — inbound webhook payload rendered as WebhookEventCard
    - ``"agent_response"`` — agent reply (rendered differently in chat UI)
    - ``"system_notification"`` — system messages (e.g. thread created)
    - ``"mcp_app_result"`` — structured MCP App result; ``event_metadata`` must
      contain at least ``{"app": "<app-name>", ...}``.
    """

    content: str
    content_type: str = "text"
    event_metadata: dict[str, Any] | None = None


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
