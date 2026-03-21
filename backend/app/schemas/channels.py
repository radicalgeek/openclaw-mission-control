"""Pydantic schemas for channel API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class ChannelBase(SQLModel):
    """Shared channel fields."""

    name: str
    description: str = ""
    channel_type: str = "discussion"
    is_readonly: bool = False
    position: int = 0


class ChannelCreate(ChannelBase):
    """Payload for creating a custom channel on a board."""

    webhook_source_filter: str | None = None


class ChannelUpdate(SQLModel):
    """Payload for updating a channel."""

    name: str | None = None
    description: str | None = None
    is_readonly: bool | None = None
    position: int | None = None


class ChannelRead(SQLModel):
    """Channel payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    name: str
    slug: str
    channel_type: str
    description: str
    is_archived: bool
    is_readonly: bool
    webhook_source_filter: str | None
    position: int
    created_at: datetime
    updated_at: datetime
    # Computed fields (may be None if not loaded)
    unread_count: int = 0
    last_message_preview: str | None = None


class ChannelWebhookInfo(SQLModel):
    """Webhook URL and secret info for a channel."""

    channel_id: UUID
    webhook_url: str | None
    webhook_secret: str


class SubscriptionUpsert(SQLModel):
    """Payload for creating or updating a channel subscription."""

    notify_on: str = "all"  # "all", "mentions", "none"


class SubscriptionRead(SQLModel):
    """Channel subscription payload."""

    id: UUID
    channel_id: UUID
    agent_id: UUID
    notify_on: str
    created_at: datetime
