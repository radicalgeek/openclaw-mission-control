"""Sprint and sprint-ticket models for backlog/sprint management."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, UniqueConstraint
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
    # status enum: draft | queued | active | reviewing | completed | cancelled
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_by_user_id: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    # Velocity snapshots (written by sprint lifecycle service at start/complete time)
    committed_minutes: int | None = Field(default=None)  # sum of estimates at sprint start
    completed_minutes: int | None = Field(default=None)  # sum of done-ticket estimates at end
    actual_minutes: int | None = Field(default=None)  # sum of done-ticket actuals at end

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


class SprintReview(TenantScoped, table=True):
    """One reviewer role's verdict for a sprint closure gate."""

    __tablename__ = "sprint_reviews"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("sprint_id", "role", name="uq_sprint_reviews_sprint_role"),
    )  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    sprint_id: UUID = Field(foreign_key="sprints.id", index=True)
    role: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    # status enum: pending | approved | changes_requested | skipped
    agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    summary: str | None = None
    findings: list[dict[str, object]] | None = Field(
        default=None,
        sa_column=Column(JSON),
    )
    created_ticket_ids: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON),
    )
    dispatched_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
