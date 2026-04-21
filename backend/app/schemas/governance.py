"""Schemas for governance policies, RBAC, and budget controls."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlmodel import SQLModel


class OrgGovernanceSettings(SQLModel):
    """Governance configuration stored in organizations.settings JSONB."""

    # Budget
    monthly_budget_usd: float | None = None
    # Model allow-list — empty means all models allowed
    allowed_models: list[str] = []
    # Skill deny-list — skills that cannot be installed in this org
    skill_deny_list: list[str] = []
    # Session TTL
    session_ttl_hours: int | None = None
    # Audit retention days (None = keep forever)
    audit_retention_days: int | None = None


class OrgGovernanceSettingsUpdate(SQLModel):
    monthly_budget_usd: float | None = None
    allowed_models: list[str] | None = None
    skill_deny_list: list[str] | None = None
    session_ttl_hours: int | None = None
    audit_retention_days: int | None = None


class BudgetStatus(SQLModel):
    """Current spend vs budget caps at different levels."""

    org_budget_usd: float | None
    org_spend_usd: float
    org_budget_pct: float | None  # 0-100 or None if no cap

    project_budgets: list["ProjectBudgetStatus"]
    agent_budgets: list["AgentBudgetStatus"]


class ProjectBudgetStatus(SQLModel):
    board_id: UUID
    board_name: str
    budget_usd: float | None
    spend_usd: float
    budget_pct: float | None


class AgentBudgetStatus(SQLModel):
    agent_id: UUID
    agent_name: str
    budget_usd: float | None
    spend_usd: float
    budget_pct: float | None


class GovernancePolicyRead(SQLModel):
    organization_id: UUID
    settings: OrgGovernanceSettings
    raw: dict[str, Any] | None = None
