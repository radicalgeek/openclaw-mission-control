"""Schemas for usage/token/cost tracking API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class UsageSnapshotRead(SQLModel):
    id: UUID
    organization_id: UUID
    gateway_id: UUID
    agent_id: UUID | None = None
    session_key: str | None = None
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    snapshot_type: str
    captured_at: datetime


class UsageSummary(SQLModel):
    """Aggregated usage totals for a given scope and time range."""

    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_usd: float
    snapshot_count: int


class UsageAgentSummary(SQLModel):
    agent_id: UUID
    agent_name: str | None = None
    total_tokens: int
    total_cost_usd: float
    snapshot_count: int


class UsageModelBreakdown(SQLModel):
    model_id: str
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_usd: float


class UsageDashboard(SQLModel):
    """Full usage dashboard payload."""

    summary: UsageSummary
    by_agent: list[UsageAgentSummary]
    by_model: list[UsageModelBreakdown]
