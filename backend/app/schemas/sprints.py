"""Schemas for sprint CRUD, lifecycle, ticket management, and webhook API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)

SprintStatus = Literal["draft", "queued", "active", "completed", "cancelled"]


class SprintCreate(SQLModel):
    """Payload for creating a new sprint."""

    name: str
    goal: str | None = None


class SprintUpdate(SQLModel):
    """Payload for partial sprint updates."""

    name: str | None = None
    goal: str | None = None
    status: Literal["queued"] | None = None  # only draft → queued allowed here
    position: int | None = None


class SprintRead(SQLModel):
    """Sprint payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    name: str
    slug: str
    goal: str | None
    position: int
    status: SprintStatus
    started_at: datetime | None
    completed_at: datetime | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    ticket_count: int = 0
    tickets_done_count: int = 0


class SprintTicketRead(SQLModel):
    """Sprint ticket link payload returned from read endpoints."""

    id: UUID
    sprint_id: UUID
    task_id: UUID
    position: int
    created_at: datetime


class SprintTicketAddRequest(SQLModel):
    """Payload for adding tasks to a sprint."""

    task_ids: list[UUID]


class SprintTicketReorderRequest(SQLModel):
    """Payload for reordering tickets within a sprint."""

    task_ids: list[UUID]


class SprintWebhookCreate(SQLModel):
    """Payload for creating a sprint webhook."""

    url: str
    events: list[str] = ["sprint_completed"]
    enabled: bool = True


class SprintWebhookUpdate(SQLModel):
    """Payload for partial sprint webhook updates."""

    url: str | None = None
    events: list[str] | None = None
    enabled: bool | None = None


class SprintWebhookRead(SQLModel):
    """Sprint webhook payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    url: str
    secret: str
    events: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime
