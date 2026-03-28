"""Thread model representing a conversation within a channel."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Thread(TenantScoped, table=True):
    """A conversation thread within a channel, optionally linked to a board task."""

    __tablename__ = "threads"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "source_type",
            "source_ref",
            name="uq_thread_channel_source_ref",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    channel_id: UUID = Field(foreign_key="channels.id", index=True)
    topic: str
    task_id: UUID | None = Field(default=None, foreign_key="tasks.id", index=True)
    # Tracks the board that "owns" this thread (set for cross-board threads in the
    # platform Support channel so the originating board lead is notified of replies).
    owner_board_id: UUID | None = Field(default=None, foreign_key="boards.id", index=True)
    source_type: str = Field(default="user", index=True)  # "user", "webhook", "agent", "system"
    source_ref: str | None = Field(default=None, index=True)
    is_resolved: bool = Field(default=False, index=True)
    is_pinned: bool = Field(default=False)
    message_count: int = Field(default=0)
    last_message_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
