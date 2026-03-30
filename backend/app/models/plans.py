"""Plan model for board-scoped planning documents."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Plan(TenantScoped, table=True):
    """A markdown planning document scoped to a board, built collaboratively with the lead agent."""

    __tablename__ = "plans"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    title: str
    slug: str = Field(index=True)
    content: str = Field(default="")
    status: str = Field(default="draft", index=True)  # "draft" | "active" | "completed" | "archived"

    created_by_user_id: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    task_id: UUID | None = Field(
        default=None,
        foreign_key="tasks.id",
        index=True,
    )

    # Gateway session for agent conversation
    session_key: str = Field(default="")

    # Chat transcript (same shape as BoardOnboardingSession.messages)
    messages: list[dict[str, object]] | None = Field(
        default=None,
        sa_column=Column(JSON),
    )

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
