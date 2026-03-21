"""UserChannelState model for tracking per-user read state on channels."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class UserChannelState(TenantScoped, table=True):
    """Per-user read state and mute preferences for a channel."""

    __tablename__ = "user_channel_states"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "channel_id",
            name="uq_user_channel_state",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    channel_id: UUID = Field(foreign_key="channels.id", index=True)
    last_read_message_id: UUID | None = Field(
        default=None, foreign_key="thread_messages.id", index=True
    )
    is_muted: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=utcnow)
