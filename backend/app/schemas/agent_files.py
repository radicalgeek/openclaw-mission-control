"""Schemas for agent workspace file list/read/write operations."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import SQLModel


class AgentFileEntry(SQLModel):
    """Metadata for a single file in an agent workspace."""

    name: str
    size: int | None = None
    modified_at: str | None = None
    missing: bool = False


class AgentFileList(SQLModel):
    """Response payload for listing agent workspace files."""

    agent_id: UUID
    gateway_agent_id: str
    files: list[AgentFileEntry]


class AgentFileContent(SQLModel):
    """Response payload for reading an agent workspace file."""

    agent_id: UUID
    gateway_agent_id: str
    name: str
    content: str


class AgentFileWrite(SQLModel):
    """Request payload for writing an agent workspace file."""

    content: str
