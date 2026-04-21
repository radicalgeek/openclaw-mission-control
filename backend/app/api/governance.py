"""Governance policy and budget control endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlmodel import col, select

from app.api.deps import require_org_admin, require_org_member
from app.core.time import utcnow
from app.db import crud
from app.db.session import get_session
from app.models.agents import Agent
from app.models.boards import Board
from app.models.usage_snapshots import UsageSnapshot
from app.schemas.governance import (
    AgentBudgetStatus,
    BudgetStatus,
    GovernancePolicyRead,
    OrgGovernanceSettings,
    OrgGovernanceSettingsUpdate,
    ProjectBudgetStatus,
)
from app.services.organizations import OrganizationContext
from app.services.telemetry.usage_rollups import aggregate_usage_window

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/governance", tags=["governance"])

SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)
ORG_ADMIN_DEP = Depends(require_org_admin)

_RUNTIME_TYPE_REFERENCES = (UUID, datetime)


def _parse_settings(raw: dict[str, object] | None) -> OrgGovernanceSettings:
    """Parse raw JSON from organizations.settings into OrgGovernanceSettings."""
    if not raw:
        return OrgGovernanceSettings()
    return OrgGovernanceSettings.model_validate(raw)


@router.get(
    "/policies",
    response_model=GovernancePolicyRead,
    tags=["governance"],
    summary="Get governance policies",
    description="Return the current governance settings for the active organization.",
)
async def get_governance_policies(
    session: "AsyncSession" = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> GovernancePolicyRead:
    """Return current governance policy settings for the org."""
    raw = ctx.organization.settings if hasattr(ctx.organization, "settings") else None
    settings = _parse_settings(raw)
    return GovernancePolicyRead(
        organization_id=ctx.organization.id,
        settings=settings,
        raw=raw,
    )


@router.put(
    "/policies",
    response_model=GovernancePolicyRead,
    tags=["governance"],
    summary="Update governance policies",
    description="Update the governance settings for the active organization. Requires admin.",
)
async def update_governance_policies(
    updates: OrgGovernanceSettingsUpdate,
    session: "AsyncSession" = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GovernancePolicyRead:
    """Update org governance policy settings."""
    existing_raw = ctx.organization.settings or {}
    current = _parse_settings(existing_raw)

    if updates.monthly_budget_usd is not None:
        current.monthly_budget_usd = updates.monthly_budget_usd
    if updates.allowed_models is not None:
        current.allowed_models = updates.allowed_models
    if updates.skill_deny_list is not None:
        current.skill_deny_list = updates.skill_deny_list
    if updates.session_ttl_hours is not None:
        current.session_ttl_hours = updates.session_ttl_hours
    if updates.audit_retention_days is not None:
        current.audit_retention_days = updates.audit_retention_days

    new_raw = current.model_dump()
    ctx.organization.settings = new_raw
    await crud.save(session, ctx.organization, commit=True)

    return GovernancePolicyRead(
        organization_id=ctx.organization.id,
        settings=current,
        raw=new_raw,
    )


@router.get(
    "/budgets",
    response_model=BudgetStatus,
    tags=["governance"],
    summary="Get budget status",
    description="Return current spend versus budget caps at org, project, and agent level.",
)
async def get_budget_status(
    session: "AsyncSession" = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> BudgetStatus:
    """Return budget utilization at org, project, and agent levels."""
    org_id = ctx.organization.id
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    snapshots = (
        await session.exec(
            select(UsageSnapshot).where(
                col(UsageSnapshot.organization_id) == org_id,
                col(UsageSnapshot.captured_at) <= now,
            )
        )
    ).all()
    usage_window = aggregate_usage_window(snapshots, since=month_start, until=now)
    org_spend = sum(item.cost_usd for item in usage_window)

    # Org budget from settings
    raw_settings = ctx.organization.settings if hasattr(ctx.organization, "settings") else None
    governance = _parse_settings(raw_settings)
    org_budget = governance.monthly_budget_usd

    def _pct(spend: float, budget: float | None) -> float | None:
        if budget is None or budget <= 0:
            return None
        return round(min(spend / budget * 100, 999.9), 1)

    boards_stmt = select(Board).where(col(Board.organization_id) == org_id)
    boards_list = (await session.exec(boards_stmt)).all()

    agent_costs: dict[UUID, float] = {}
    gateway_unattributed_costs: dict[UUID, float] = {}
    for item in usage_window:
        if item.agent_id is not None:
            agent_costs[item.agent_id] = agent_costs.get(item.agent_id, 0.0) + item.cost_usd
        else:
            gateway_unattributed_costs[item.gateway_id] = (
                gateway_unattributed_costs.get(item.gateway_id, 0.0) + item.cost_usd
            )

    gateway_board_counts: dict[UUID, int] = {}
    for board in boards_list:
        if board.gateway_id is not None:
            gateway_board_counts[board.gateway_id] = (
                gateway_board_counts.get(board.gateway_id, 0) + 1
            )

    project_budgets: list[ProjectBudgetStatus] = []
    for board in boards_list:
        budget_usd = board.budget_usd
        if budget_usd is None:
            continue
        board_agent_ids_stmt = select(Agent.id).where(col(Agent.board_id) == board.id)
        board_agent_ids = list((await session.exec(board_agent_ids_stmt)).all())
        board_spend = sum(agent_costs.get(agent_id, 0.0) for agent_id in board_agent_ids)
        if board.gateway_id is not None and gateway_board_counts.get(board.gateway_id) == 1:
            board_spend += gateway_unattributed_costs.get(board.gateway_id, 0.0)
        project_budgets.append(
            ProjectBudgetStatus(
                board_id=board.id,
                board_name=board.name,
                budget_usd=float(budget_usd),
                spend_usd=board_spend,
                budget_pct=_pct(board_spend, float(budget_usd)),
            )
        )

    from sqlalchemy import and_

    # Per-agent spend — scoped to boards in this org
    all_agents_stmt = select(Agent).where(
        and_(
            col(Agent.budget_usd).is_not(None),
            col(Agent.board_id).in_(select(Board.id).where(col(Board.organization_id) == org_id)),
        )
    )
    agents_with_budget = (await session.exec(all_agents_stmt)).all()
    agent_budgets: list[AgentBudgetStatus] = []
    for agent in agents_with_budget:
        budget_value = agent.budget_usd
        if budget_value is None:
            continue
        agent_spend = agent_costs.get(agent.id, 0.0)
        agent_budgets.append(
            AgentBudgetStatus(
                agent_id=agent.id,
                agent_name=agent.name,
                budget_usd=float(budget_value),
                spend_usd=agent_spend,
                budget_pct=_pct(agent_spend, float(budget_value)),
            )
        )

    return BudgetStatus(
        org_budget_usd=org_budget,
        org_spend_usd=org_spend,
        org_budget_pct=_pct(org_spend, org_budget),
        project_budgets=project_budgets,
        agent_budgets=agent_budgets,
    )
