"""Reusable FastAPI dependencies for auth and board/task access.

These dependencies are the main "policy wiring" layer for the API.

They:
- resolve the authenticated actor (human user vs agent)
- enforce organization/board access rules
- provide common "load or 404" helpers (board/task)

Why this exists:
- Keeping authorization logic centralized makes it easier to reason about (and
  audit) permissions as the API surface grows.
- Some routes allow either human users or agents; others require user auth.

If you're adding a new endpoint, prefer composing from these dependencies instead
of re-implementing permission checks in the router.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import col, select

from app.core.agent_auth import get_agent_auth_context_optional
from app.core.auth import AuthContext, get_auth_context, get_auth_context_optional
from app.db.session import get_session
from app.models.agent_board_access import ACCESS_LEVEL_WRITE, AgentBoardAccess
from app.models.agents import AGENT_TYPE_STANDALONE
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.schemas.agents import STANDALONE_ROLE_TEMPLATES
from app.services.admin_access import require_user_actor
from app.services.organizations import (
    CAPABILITY_EXPORT_COMPLIANCE_ROLES,
    CAPABILITY_VIEW_AUDIT_ROLES,
    OrganizationContext,
    ensure_member_for_user,
    get_active_membership,
    has_capability,
    is_org_admin,
    require_board_access,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.agents import Agent
    from app.models.users import User

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


def require_user_auth(auth: AuthContext = AUTH_DEP) -> AuthContext:
    """Require an authenticated human user (not an agent)."""
    require_user_actor(auth)
    return auth


@dataclass
class ActorContext:
    """Authenticated actor context for user or agent callers."""

    actor_type: Literal["user", "agent"]
    user: User | None = None
    agent: Agent | None = None


async def require_user_or_agent(
    request: Request,
    session: AsyncSession = SESSION_DEP,
) -> ActorContext:
    """Authorize either a human user or an authenticated agent.

    User auth is resolved first so normal bearer-token user traffic does not
    also trigger agent-token verification on mixed user/agent routes.
    """
    auth = await get_auth_context_optional(
        request=request,
        credentials=None,
        session=session,
    )
    if auth is not None:
        require_user_actor(auth)
        return ActorContext(actor_type="user", user=auth.user)
    agent_auth = await get_agent_auth_context_optional(
        request=request,
        agent_token=request.headers.get("X-Agent-Token"),
        authorization=request.headers.get("Authorization"),
        session=session,
    )
    if agent_auth is not None:
        return ActorContext(actor_type="agent", agent=agent_auth.agent)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


ACTOR_DEP = Depends(require_user_or_agent)


async def agent_has_board_access(
    session: AsyncSession,
    *,
    agent: Agent,
    board: Board,
    write: bool,
) -> bool:
    """Return whether an agent may access a board at the requested level.

    Rules:
    - board-scoped agents may only access their own board
    - standalone agents in ``STANDALONE_ROLE_TEMPLATES`` (Triager, Planner,
      Estimator, Priority, Quality Reviewer, Security Reviewer, Architecture
      Reviewer, etc.) are organization-level helpers — they get write access
      to every board within their gateway's organization without needing
      explicit ``AgentBoardAccess`` grants.
    - other standalone agents (custom / non-templated) still need an explicit
      ``agent_board_access`` grant.
    - other boardless agents are scoped to their gateway organization
    """
    if agent.board_id is not None:
        return agent.board_id == board.id

    if agent.agent_type == AGENT_TYPE_STANDALONE:
        # Org-level templated agents (triager, planner, estimator, priority,
        # quality_reviewer, security_reviewer, architecture_reviewer, etc.)
        # are designed to operate across every board in their gateway's
        # organization. Grant org-membership access automatically without
        # requiring an explicit AgentBoardAccess row per (agent, board) pair.
        profile = agent.identity_profile or {}
        role_template = profile.get("role_template")
        if (
            role_template
            and role_template in STANDALONE_ROLE_TEMPLATES
            and agent.gateway_id is not None
        ):
            gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
            if gateway is not None and gateway.organization_id == board.organization_id:
                return True
            # Fall through to explicit-grant lookup if org check fails.
        grant = (
            await session.exec(
                select(AgentBoardAccess).where(
                    col(AgentBoardAccess.agent_id) == agent.id,
                    col(AgentBoardAccess.board_id) == board.id,
                )
            )
        ).first()
        if grant is None:
            return False
        return not write or grant.access_level == ACCESS_LEVEL_WRITE

    gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
    return gateway is not None and gateway.organization_id == board.organization_id


async def require_org_member(
    auth: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OrganizationContext:
    """Resolve and require active organization membership for the current user."""
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    member = await get_active_membership(session, auth.user)
    if member is None:
        member = await ensure_member_for_user(session, auth.user)
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    organization = await Organization.objects.by_id(member.organization_id).first(
        session,
    )
    if organization is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return OrganizationContext(organization=organization, member=member)


ORG_MEMBER_DEP = Depends(require_org_member)


async def require_org_admin(
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> OrganizationContext:
    """Require organization-admin membership privileges."""
    if not is_org_admin(ctx.member):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return ctx


async def require_audit_access(
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> OrganizationContext:
    """Require audit/usage read access (owner, admin, operator, or auditor)."""
    if not has_capability(ctx.member, CAPABILITY_VIEW_AUDIT_ROLES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return ctx


async def require_compliance_export(
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> OrganizationContext:
    """Require compliance export access (owner, admin, or auditor)."""
    if not has_capability(ctx.member, CAPABILITY_EXPORT_COMPLIANCE_ROLES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return ctx


@dataclass
class IngestCallerContext:
    """Resolved caller context for telemetry ingest endpoints.

    Supports both agent-token callers (pod sidecars) and human org-member callers.
    When called by an agent, organization_id and gateway_id are resolved from the
    agent's gateway record so data is fully attributed.
    """

    organization_id: UUID
    agent_id: UUID | None  # None when called by a human operator
    gateway_id: UUID | None  # None when called by a human operator


async def require_ingest_caller(
    request: Request,
    session: AsyncSession = SESSION_DEP,
) -> IngestCallerContext:
    """Accept agent-token or user-org-member auth for telemetry ingest endpoints.

    Agent callers (sidecars) use ``X-Agent-Token``; their organization and gateway
    are resolved automatically from the authenticated agent record.
    Human callers fall back to the standard org-member dep so operators can also
    submit ingest payloads for agents they manage.
    """
    agent_auth = await get_agent_auth_context_optional(
        request=request,
        agent_token=request.headers.get("X-Agent-Token"),
        authorization=request.headers.get("Authorization"),
        session=session,
    )
    if agent_auth is not None:
        agent = agent_auth.agent
        gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
        if gateway is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gateway not found")
        return IngestCallerContext(
            organization_id=gateway.organization_id,
            agent_id=agent.id,
            gateway_id=gateway.id,
        )
    # Fall back to human user org-member auth
    auth_ctx = await get_auth_context_optional(
        request=request,
        credentials=None,
        session=session,
    )
    if auth_ctx is None or auth_ctx.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    member = await get_active_membership(session, auth_ctx.user)
    if member is None:
        member = await ensure_member_for_user(session, auth_ctx.user)
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    organization = await Organization.objects.by_id(member.organization_id).first(session)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return IngestCallerContext(
        organization_id=organization.id,
        agent_id=None,
        gateway_id=None,
    )


async def get_board_or_404(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
) -> Board:
    """Load a board by id or raise HTTP 404."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return board


async def get_board_for_actor_read(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> Board:
    """Load a board and enforce actor read access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if actor.actor_type == "agent":
        if actor.agent is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        allowed = await agent_has_board_access(
            session,
            agent=actor.agent,
            board=board,
            write=False,
        )
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return board
    if actor.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=actor.user, board=board, write=False)
    return board


async def get_board_for_actor_write(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> Board:
    """Load a board and enforce actor write access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if actor.actor_type == "agent":
        if actor.agent is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        allowed = await agent_has_board_access(
            session,
            agent=actor.agent,
            board=board,
            write=True,
        )
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return board
    if actor.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=actor.user, board=board, write=True)
    return board


async def get_board_for_user_read(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
) -> Board:
    """Load a board and enforce authenticated-user read access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=False)
    return board


async def get_board_for_user_write(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
) -> Board:
    """Load a board and enforce authenticated-user write access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=True)
    return board


BOARD_READ_DEP = Depends(get_board_for_actor_read)


async def get_task_or_404(
    task_id: UUID,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> Task:
    """Load a task for a board or raise HTTP 404."""
    task = await Task.objects.by_id(task_id).first(session)
    if task is None or task.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return task
