"""Schemas for board-level and org-level agent template overrides."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel


class BoardTemplateRead(SQLModel):
    """Response payload for a single board template override."""

    id: UUID
    organization_id: UUID
    board_id: UUID | None = None
    file_name: str
    template_content: str
    description: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    # Human-readable source label for the UI
    source: str = "board"  # "board" | "org" | "built-in"


class BoardTemplateUpsert(SQLModel):
    """Request payload for creating or updating a board template override."""

    template_content: str
    description: str | None = None


class BoardTemplatePreviewRequest(SQLModel):
    """Request payload for previewing a Jinja2 template render."""

    template_content: str
    # Optionally specify an agent ID to render with real context.
    # If omitted a syntax-check-only render is performed with a stub context.
    agent_id: UUID | None = None


class BoardTemplatePreviewResponse(SQLModel):
    """Response payload for a template preview render."""

    rendered: str
    warnings: list[str] = []
