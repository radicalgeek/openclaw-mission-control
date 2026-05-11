"""Schemas for sprint review gate API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)

SprintReviewRole = Literal["qa", "security", "architecture"]
SprintReviewStatus = Literal["pending", "approved", "changes_requested", "skipped"]
SprintReviewVerdict = Literal["approve", "changes_requested"]


class SprintReviewRead(SQLModel):
    """A single reviewer role's status for a sprint."""

    id: UUID
    board_id: UUID
    sprint_id: UUID
    role: SprintReviewRole
    status: SprintReviewStatus
    agent_id: UUID | None = None
    summary: str | None = None
    findings: list[dict[str, object]] | None = None
    created_ticket_ids: list[str] | None = None
    dispatched_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SprintReviewUpdate(SQLModel):
    """Agent-submitted sprint review verdict."""

    verdict: SprintReviewVerdict
    summary: str = ""
    findings: list[dict[str, object]] | None = None
    created_ticket_ids: list[str] | None = None


class SprintReviewGateRead(SQLModel):
    """Aggregated review gate status for a sprint."""

    sprint_id: UUID
    status: str
    approved: bool
    reviews: list[SprintReviewRead]
