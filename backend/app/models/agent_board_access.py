"""Board access grants for standalone agents."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)

ACCESS_LEVEL_READ = "read"
ACCESS_LEVEL_WRITE = "write"


class AgentBoardAccess(QueryModel, table=True):
    """Explicit board access grant for a standalone agent."""

    __tablename__ = "agent_board_access"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("agent_id", "board_id", name="uq_agent_board_access"),
    )  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agents.id", index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    access_level: str = Field(default=ACCESS_LEVEL_READ, index=True)
    created_at: datetime = Field(default_factory=utcnow)
