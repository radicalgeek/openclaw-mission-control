"""Agent skill allowlist management endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import SQLModel

from app.api.deps import require_org_admin
from app.db.session import get_session
from app.models.agents import Agent
from app.services.organizations import OrganizationContext

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/agents/{agent_id}/skills", tags=["agent-skills"])
SESSION_DEP = Depends(get_session)
ORG_ADMIN_DEP = Depends(require_org_admin)


class AgentSkillsRead(SQLModel):
    """Agent skill allowlist response."""

    agent_id: UUID
    installed_skills: list[str] | None = None


class AgentSkillsUpdate(SQLModel):
    """Payload for updating agent skill allowlist."""

    installed_skills: list[str] | None = None


@router.get("", response_model=AgentSkillsRead)
async def get_agent_skills(
    agent_id: UUID,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AgentSkillsRead:
    """Get the skill allowlist for an agent."""
    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return AgentSkillsRead(agent_id=agent.id, installed_skills=agent.installed_skills)


@router.patch("", response_model=AgentSkillsRead)
async def update_agent_skills(
    agent_id: UUID,
    payload: AgentSkillsUpdate,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AgentSkillsRead:
    """Update the skill allowlist for an agent.

    Updates ``installed_skills`` on the agent record.

    - ``null``: inherit gateway defaults (no allowlist enforcement)
    - ``[]``: no skills (empty allowlist)
    - ``["a", "b"]``: explicit allowlist

    Note: the allowlist is stored on the agent record and will be forwarded to
    the gateway when full skill-provisioning integration is enabled.
    """
    from app.core.time import utcnow

    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    agent.installed_skills = payload.installed_skills
    agent.updated_at = utcnow()
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    return AgentSkillsRead(agent_id=agent.id, installed_skills=agent.installed_skills)
