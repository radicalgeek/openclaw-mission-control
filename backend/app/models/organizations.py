"""Organization model representing top-level tenant entities."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Column, Field, JSON

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Organization(QueryModel, table=True):
    """Top-level organization tenant record."""

    __tablename__ = "organizations"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    branding_overrides: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
