"""BoardTemplate model for DB-stored per-board and org-level template overrides."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel


class BoardTemplate(QueryModel, table=True):
    """Jinja2 template override stored in the DB for a board or organization.

    Resolution cascade at sync time:
    1. Per-agent override (Agent.identity_template / Agent.soul_template)
    2. Board-scoped override (board_id is NOT NULL)
    3. Org-wide default (board_id IS NULL)
    4. Built-in .j2 file on disk (backend/templates/)
    """

    __tablename__ = "board_templates"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "board_id",
            "file_name",
            name="uq_board_templates_org_board_file",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    board_id: UUID | None = Field(default=None, foreign_key="boards.id", index=True, nullable=True)
    file_name: str = Field(index=True)
    template_content: str = Field(sa_column=Column(Text))
    description: str | None = Field(default=None, sa_column=Column(Text))
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
