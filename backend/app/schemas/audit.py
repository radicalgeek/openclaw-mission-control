"""Schemas for the agent audit log API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class AuditLogRead(SQLModel):
    id: UUID
    organization_id: UUID
    gateway_id: UUID | None = None
    board_id: UUID | None = None
    agent_id: UUID | None = None
    task_id: UUID | None = None
    session_key: str | None = None
    thread_id: UUID | None = None
    sprint_id: UUID | None = None
    event_category: str
    event_action: str
    detail: dict[str, Any] | None = None
    token_input: int | None = None
    token_output: int | None = None
    cost_usd: float | None = None
    model_id: str | None = None
    correlation_id: str | None = None
    source: str
    actor_type: str
    actor_id: UUID | None = None
    ip_address: str | None = None
    created_at: datetime


class CommandIngestItem(SQLModel):
    """A single command-logger event from the OpenClaw pod."""

    session_key: str | None = None
    agent_id: UUID | None = None
    tool_name: str
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    model_id: str | None = None
    token_input: int | None = None
    token_output: int | None = None
    cost_usd: float | None = None
    correlation_id: str | None = None
    occurred_at: datetime | None = None


class CommandIngestRequest(SQLModel):
    """Batch command-logger ingest payload."""

    commands: list[CommandIngestItem]


class UsageIngestItem(SQLModel):
    """Agent-self-reported usage for a single turn."""

    session_key: str | None = None
    model_id: str
    token_input: int = 0
    token_output: int = 0
    cost_usd: float = 0.0
    occurred_at: datetime | None = None


class UsageIngestRequest(SQLModel):
    """Batch agent self-reported usage ingest payload."""

    items: list[UsageIngestItem]
