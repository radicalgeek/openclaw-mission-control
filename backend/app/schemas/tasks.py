"""Schemas for task CRUD and task comment API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlmodel import Field, SQLModel

from app.schemas.common import NonEmptyStr
from app.schemas.tags import TagRef
from app.schemas.task_custom_fields import TaskCustomFieldValues

TaskStatus = Literal["triage", "backlog", "inbox", "in_progress", "review", "done", "archived"]
STATUS_REQUIRED_ERROR = "status is required"

# Lifecycle order — used for documentation and agent templates
# triage → backlog → inbox → in_progress → review → done → archived

# Status transition rules: maps a status to the set of valid *next* statuses
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "triage": frozenset({"backlog", "archived"}),
    "backlog": frozenset({"inbox", "triage", "archived"}),
    "inbox": frozenset({"in_progress", "backlog"}),
    "in_progress": frozenset({"review", "inbox"}),
    "review": frozenset({"done", "in_progress", "inbox"}),  # inbox = kick-back when blocked
    "done": frozenset({"archived", "in_progress"}),
    "archived": frozenset({"backlog"}),
}

# Priority string → auto-rescore midpoint
_PRIORITY_SCORE_DEFAULTS: dict[str, int] = {
    "low": 15,
    "medium": 35,
    "high": 65,
    "critical": 90,
}


def priority_to_score(priority: str) -> int:
    """Return the midpoint priority_score for a given priority string label."""
    return _PRIORITY_SCORE_DEFAULTS.get(priority, 35)


# Keep these symbols as runtime globals so Pydantic can resolve
# deferred annotations reliably.
RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr, TagRef)


class TaskBase(SQLModel):
    """Shared task fields used by task create/read payloads."""

    title: str
    description: str | None = None
    status: TaskStatus = "inbox"
    priority: str = "medium"  # Display label: low / medium / high / critical
    priority_score: int = 35  # Numeric 1–100 for ordering; auto-set if not provided
    due_at: datetime | None = None
    assigned_agent_id: UUID | None = None
    depends_on_task_ids: list[UUID] = Field(default_factory=list)
    tag_ids: list[UUID] = Field(default_factory=list)
    estimate_minutes: int | None = None
    actual_minutes: int | None = None
    plan_id: UUID | None = None


class TaskCreate(TaskBase):
    """Payload for creating a task."""

    created_by_user_id: UUID | None = None
    custom_field_values: TaskCustomFieldValues = Field(default_factory=dict)
    is_backlog: bool = False

    @model_validator(mode="after")
    def auto_rescore_on_create(self) -> Self:
        """If priority_score was not explicitly provided, derive it from the priority label."""
        if "priority_score" not in self.model_fields_set:
            self.priority_score = priority_to_score(self.priority)
        return self


class TaskUpdate(SQLModel):
    """Payload for partial task updates."""

    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: str | None = None
    priority_score: int | None = None
    due_at: datetime | None = None
    assigned_agent_id: UUID | None = None
    depends_on_task_ids: list[UUID] | None = None
    tag_ids: list[UUID] | None = None
    custom_field_values: TaskCustomFieldValues | None = None
    comment: NonEmptyStr | None = None
    estimate_minutes: int | None = None
    actual_minutes: int | None = None

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: object) -> object | None:
        """Normalize blank comment strings to `None`."""
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_status_and_rescore(self) -> Self:
        """Ensure explicitly supplied status is not null; auto-rescore priority if changed."""
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError(STATUS_REQUIRED_ERROR)
        # When priority label changes but score is not explicitly provided, auto-rescore
        if (
            "priority" in self.model_fields_set
            and self.priority is not None
            and "priority_score" not in self.model_fields_set
        ):
            self.priority_score = priority_to_score(self.priority)
        return self


class ChannelInfo(SQLModel):
    """Minimal channel info attached to a task when it has a linked thread."""

    channel_id: UUID
    channel_name: str
    channel_slug: str


class TaskRead(TaskBase):
    """Task payload returned from read endpoints."""

    id: UUID
    board_id: UUID | None
    created_by_user_id: UUID | None
    in_progress_at: datetime | None
    done_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    blocked_by_task_ids: list[UUID] = Field(default_factory=list)
    is_blocked: bool = False
    tags: list[TagRef] = Field(default_factory=list)
    custom_field_values: TaskCustomFieldValues | None = None
    # Channel thread link (None for legacy tasks without a linked thread)
    thread_id: UUID | None = None
    channel_info: ChannelInfo | None = None
    is_backlog: bool = False
    sprint_id: UUID | None = None
    plan_id: UUID | None = None


class TaskCommentCreate(SQLModel):
    """Payload for creating a task comment."""

    message: NonEmptyStr


class TaskCommentRead(SQLModel):
    """Task comment payload returned from read endpoints."""

    id: UUID
    message: str | None
    agent_id: UUID | None
    task_id: UUID | None
    created_at: datetime
