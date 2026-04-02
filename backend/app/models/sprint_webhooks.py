"""Sprint webhook configuration model for outbound lifecycle event notifications."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


class SprintWebhook(TenantScoped, table=True):
    """Outbound webhook endpoint fired on sprint lifecycle events."""

    __tablename__ = "sprint_webhooks"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    url: str
    secret: str  # HMAC signing secret (auto-generated, stored plain)
    events: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON),
    )
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
