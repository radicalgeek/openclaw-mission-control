"""Channel model for board-scoped messaging channels."""

from __future__ import annotations

import secrets
from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped

RUNTIME_ANNOTATION_TYPES = (datetime,)


def _generate_webhook_secret() -> str:
    return secrets.token_hex(32)


class Channel(TenantScoped, table=True):
    """A messaging channel scoped to a board (alert or discussion type)."""

    __tablename__ = "channels"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    name: str
    slug: str = Field(index=True)
    channel_type: str = Field(default="discussion", index=True)  # "alert" or "discussion"
    description: str = Field(default="")
    is_archived: bool = Field(default=False, index=True)
    is_readonly: bool = Field(default=False)
    webhook_source_filter: str | None = Field(default=None, index=True)
    webhook_secret: str = Field(default_factory=_generate_webhook_secret)
    position: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
