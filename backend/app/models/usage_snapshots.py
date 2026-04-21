"""Usage snapshot model — cumulative token/cost snapshots per gateway/agent/model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, Numeric, Text
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)

SNAPSHOT_TYPE_PERIODIC = "periodic"
SNAPSHOT_TYPE_SESSION_END = "session_end"
SNAPSHOT_TYPE_AGENT_REPORT = "agent_report"


class UsageSnapshot(QueryModel, table=True):
    """Cumulative token/cost snapshot captured from the gateway."""

    __tablename__ = "usage_snapshots"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    gateway_id: UUID = Field(foreign_key="gateways.id", index=True)
    agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    session_key: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    model_id: str = Field(default="unknown")
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    cost_usd: float = Field(default=0, sa_column=Column(Numeric(12, 6), nullable=False))
    snapshot_type: str = Field(default=SNAPSHOT_TYPE_PERIODIC, index=True)
    captured_at: datetime = Field(default_factory=utcnow, index=True)
