"""Schemas for agent board access grants."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)

ACCESS_LEVELS = frozenset({"read", "write"})


class AgentBoardAccessCreate(SQLModel):
    """Payload for granting a standalone agent access to a board."""

    board_id: UUID
    access_level: str = "read"

    def model_post_init(self, __context: object) -> None:
        if self.access_level not in ACCESS_LEVELS:
            msg = f"access_level must be one of: {sorted(ACCESS_LEVELS)}"
            raise ValueError(msg)


class AgentBoardAccessRead(SQLModel):
    """Serialized board access grant for a standalone agent."""

    id: UUID
    agent_id: UUID
    board_id: UUID
    access_level: str
    created_at: datetime
