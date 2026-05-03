"""Agent board access grant management endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import require_org_admin
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agent_board_access import AgentBoardAccess
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.boards import Board
from app.schemas.agent_board_access import AgentBoardAccessCreate, AgentBoardAccessRead
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.organizations import OrganizationContext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/agents/{agent_id}/board-access", tags=["agent-board-access"])

SESSION_DEP = Depends(get_session)
ORG_ADMIN_DEP = Depends(require_org_admin)


def _to_read(grant: AgentBoardAccess) -> AgentBoardAccessRead:
    return AgentBoardAccessRead.model_validate(grant, from_attributes=True)


async def _require_standalone_agent(
    session: AsyncSession,
    *,
    agent_id: UUID,
    ctx: OrganizationContext,
) -> Agent:
    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if agent.agent_type != AGENT_TYPE_STANDALONE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Board access grants are only supported for standalone agents",
        )
    return agent


@router.get("", response_model=DefaultLimitOffsetPage[AgentBoardAccessRead])
async def list_board_access(
    agent_id: UUID,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> LimitOffsetPage[AgentBoardAccessRead]:
    """List all board access grants for a standalone agent."""
    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    statement = (
        select(AgentBoardAccess)
        .where(col(AgentBoardAccess.agent_id) == agent_id)
        .order_by(col(AgentBoardAccess.created_at).desc())
    )

    def _transform(items: Sequence[object]) -> Sequence[object]:
        grants = [item for item in items if isinstance(item, AgentBoardAccess)]
        return [_to_read(g) for g in grants]

    return await paginate(session, statement, transformer=_transform)


@router.post("", response_model=AgentBoardAccessRead)
async def grant_board_access(
    agent_id: UUID,
    payload: AgentBoardAccessCreate,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AgentBoardAccessRead:
    """Grant a standalone agent access to a board.

    Idempotent: if an active grant already exists for the (agent, board) pair,
    the existing grant is returned and the access_level is upgraded to
    ``write`` if the existing grant is ``read`` and the request asks for
    ``write``. Downgrades from write to read are ignored.
    """
    agent = await _require_standalone_agent(session, agent_id=agent_id, ctx=ctx)

    board = await Board.objects.by_id(payload.board_id).first(session)
    if board is None or board.organization_id != ctx.organization.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Board not found",
        )

    existing = (
        await session.exec(
            select(AgentBoardAccess)
            .where(col(AgentBoardAccess.agent_id) == agent.id)
            .where(col(AgentBoardAccess.board_id) == board.id),
        )
    ).first()
    if existing is not None:
        if existing.access_level == "read" and payload.access_level == "write":
            existing.access_level = "write"
            await crud.save(session, existing)
        return _to_read(existing)

    grant = AgentBoardAccess(
        agent_id=agent.id,
        board_id=board.id,
        access_level=payload.access_level,
    )
    await crud.save(session, grant)
    return _to_read(grant)


@router.delete("", response_model=OkResponse)
async def revoke_board_access_by_board(
    agent_id: UUID,
    board_id: UUID = Query(..., description="Board ID to revoke access from"),
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OkResponse:
    """Revoke a standalone agent's access to a specific board.

    Idempotent: returns 200 even if no grant exists for the pair. Used by
    automation that grants access for a unit of work and revokes it
    afterwards without tracking the grant_id.
    """
    grant = (
        await session.exec(
            select(AgentBoardAccess)
            .where(col(AgentBoardAccess.agent_id) == agent_id)
            .where(col(AgentBoardAccess.board_id) == board_id),
        )
    ).first()
    if grant is not None:
        # Verify the board belongs to the requester's org before revoking.
        board = await Board.objects.by_id(board_id).first(session)
        if board is None or board.organization_id != ctx.organization.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Board not found",
            )
        await session.delete(grant)
        await session.commit()
    return OkResponse()


@router.delete("/{grant_id}", response_model=OkResponse)
async def revoke_board_access(
    agent_id: UUID,
    grant_id: UUID,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OkResponse:
    """Revoke a board access grant from a standalone agent."""
    grant = (
        await session.exec(
            select(AgentBoardAccess)
            .where(col(AgentBoardAccess.id) == grant_id)
            .where(col(AgentBoardAccess.agent_id) == agent_id),
        )
    ).first()
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await session.delete(grant)
    await session.commit()
    return OkResponse()
