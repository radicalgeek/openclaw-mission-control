"""Sprint and sprint-ticket models for backlog/sprint management."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Sprint(TenantScoped, table=True):
    """A time-boxed sprint grouping backlog tickets for a board."""

    __tablename__ = "sprints"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    name: str
    slug: str = Field(index=True)
    goal: str | None = None
    position: int = Field(default=0)
    status: str = Field(default="draft", index=True)
    # status enum: draft | queued | active | completed | cancelled
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_by_user_id: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SprintTicket(TenantScoped, table=True):
    """Links a backlog task to a sprint with ordering."""

    __tablename__ = "sprint_tickets"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    sprint_id: UUID = Field(foreign_key="sprints.id", index=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    position: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
