"""Usage/token/cost dashboard endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlmodel import col, select

from app.api.deps import require_org_member
from app.db.session import get_session
from app.models.agents import Agent
from app.models.usage_snapshots import UsageSnapshot
from app.schemas.usage import (
    UsageAgentSummary,
    UsageDashboard,
    UsageModelBreakdown,
    UsageSnapshotRead,
    UsageSummary,
)
from app.services.organizations import OrganizationContext
from app.services.telemetry.usage_rollups import aggregate_usage_window, count_window_snapshots

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/usage", tags=["usage"])

SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)

_RUNTIME_TYPE_REFERENCES = (UUID, datetime)


@router.get("", response_model=UsageDashboard, tags=["usage"])
async def get_usage_dashboard(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    board_id: UUID | None = Query(default=None),
    session: "AsyncSession" = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> UsageDashboard:
    """Aggregated token/cost data by org, model, and agent."""
    filters = [col(UsageSnapshot.organization_id) == ctx.organization.id]
    if until is not None:
        filters.append(col(UsageSnapshot.captured_at) <= until)
    if board_id is not None:
        # Resolve agent IDs on this board and filter snapshots by those agents.
        from sqlmodel import col as _col

        from app.models.agents import Agent as _Agent

        board_agent_ids_stmt = select(_Agent.id).where(_col(_Agent.board_id) == board_id)
        filters.append(col(UsageSnapshot.agent_id).in_(board_agent_ids_stmt))

    from sqlalchemy import and_

    snapshots = (await session.exec(select(UsageSnapshot).where(and_(*filters)))).all()
    aggregates = aggregate_usage_window(snapshots, since=since, until=until)
    snapshot_count = count_window_snapshots(snapshots, since=since, until=until)

    summary = UsageSummary(
        total_prompt_tokens=sum(item.prompt_tokens for item in aggregates),
        total_completion_tokens=sum(item.completion_tokens for item in aggregates),
        total_tokens=sum(item.total_tokens for item in aggregates),
        total_cost_usd=sum(item.cost_usd for item in aggregates),
        snapshot_count=snapshot_count,
    )

    agent_totals: dict[UUID, dict[str, float | int]] = {}
    for item in aggregates:
        if item.agent_id is None:
            continue
        current = agent_totals.setdefault(
            item.agent_id,
            {"total_tokens": 0, "total_cost": 0.0, "count": 0},
        )
        current["total_tokens"] = int(current["total_tokens"]) + item.total_tokens
        current["total_cost"] = float(current["total_cost"]) + item.cost_usd
        current["count"] = int(current["count"]) + 1

    # Load agent names
    agent_ids = list(agent_totals)
    agent_names: dict[UUID, str] = {}
    if agent_ids:
        name_stmt = select(Agent.id, Agent.name).where(col(Agent.id).in_(agent_ids))
        for a_id, a_name in (await session.exec(name_stmt)).all():
            agent_names[a_id] = a_name

    by_agent = sorted(
        [
            UsageAgentSummary(
                agent_id=agent_id,
                agent_name=agent_names.get(agent_id),
                total_tokens=int(values["total_tokens"]),
                total_cost_usd=float(values["total_cost"]),
                snapshot_count=int(values["count"]),
            )
            for agent_id, values in agent_totals.items()
        ],
        key=lambda item: item.total_cost_usd,
        reverse=True,
    )

    model_totals: dict[str, dict[str, float | int]] = {}
    for item in aggregates:
        current = model_totals.setdefault(
            item.model_id,
            {
                "total_prompt": 0,
                "total_completion": 0,
                "total_tokens": 0,
                "total_cost": 0.0,
            },
        )
        current["total_prompt"] = int(current["total_prompt"]) + item.prompt_tokens
        current["total_completion"] = int(current["total_completion"]) + item.completion_tokens
        current["total_tokens"] = int(current["total_tokens"]) + item.total_tokens
        current["total_cost"] = float(current["total_cost"]) + item.cost_usd

    by_model = sorted(
        [
            UsageModelBreakdown(
                model_id=model_id,
                total_prompt_tokens=int(values["total_prompt"]),
                total_completion_tokens=int(values["total_completion"]),
                total_tokens=int(values["total_tokens"]),
                total_cost_usd=float(values["total_cost"]),
            )
            for model_id, values in model_totals.items()
        ],
        key=lambda item: item.total_tokens,
        reverse=True,
    )

    return UsageDashboard(summary=summary, by_agent=by_agent, by_model=by_model)


@router.get("/agents/{agent_id}", response_model=list[UsageSnapshotRead], tags=["usage"])
async def get_agent_usage(
    agent_id: UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    session: "AsyncSession" = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> list[UsageSnapshotRead]:
    """Per-agent usage snapshot history."""
    from sqlalchemy import and_

    filters = [
        col(UsageSnapshot.organization_id) == ctx.organization.id,
        col(UsageSnapshot.agent_id) == agent_id,
    ]
    if since is not None:
        filters.append(col(UsageSnapshot.captured_at) >= since)
    if until is not None:
        filters.append(col(UsageSnapshot.captured_at) <= until)

    stmt = (
        select(UsageSnapshot)
        .where(and_(*filters))
        .order_by(col(UsageSnapshot.captured_at).desc())
        .limit(200)
    )
    rows = (await session.exec(stmt)).all()
    return [UsageSnapshotRead.model_validate(r, from_attributes=True) for r in rows]
