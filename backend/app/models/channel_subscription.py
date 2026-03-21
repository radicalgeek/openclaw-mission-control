"""ChannelSubscription model for agent subscriptions to channels."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class ChannelSubscription(TenantScoped, table=True):
    """Tracks which agents are subscribed to a channel and their notification preferences."""

    __tablename__ = "channel_subscriptions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "agent_id",
            name="uq_channel_subscription_agent",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    channel_id: UUID = Field(foreign_key="channels.id", index=True)
    agent_id: UUID = Field(foreign_key="agents.id", index=True)
    notify_on: str = Field(default="all")  # "all", "mentions", "none"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
