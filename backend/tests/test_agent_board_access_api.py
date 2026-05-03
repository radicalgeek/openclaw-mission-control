# ruff: noqa: INP001
"""Tests for the standalone-agent board access grant API.

Covers idempotent grant, revoke-by-grant-id, and revoke-by-board-id paths.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.agent_board_access import router as access_router
from app.api.deps import require_org_admin
from app.db.session import get_session
from app.models.agent_board_access import AgentBoardAccess
from app.models.agents import (
    AGENT_TYPE_BOARD_WORKER,
    AGENT_TYPE_STANDALONE,
    Agent,
)
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.services.organizations import OrganizationContext


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_app(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    org_ctx: OrganizationContext,
) -> FastAPI:
    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(access_router)
    app.include_router(api)

    async def _session_override():
        async with session_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[require_org_admin] = lambda: org_ctx
    return app


async def _seed(
    session: AsyncSession,
    *,
    standalone: bool = True,
) -> tuple[OrganizationContext, Agent, Board]:
    org = Organization(id=uuid4(), name=f"org-{uuid4()}")
    member = OrganizationMember(organization_id=org.id, user_id=uuid4(), role="admin")
    gateway = Gateway(
        id=uuid4(),
        organization_id=org.id,
        name="gw",
        url="https://gw.example",
        token="t",
        workspace_root="/tmp/ws",
    )
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        name="b",
        slug=f"b-{uuid4()}",
        gateway_id=gateway.id,
    )
    agent = Agent(
        id=uuid4(),
        gateway_id=gateway.id,
        name="planner",
        agent_type=AGENT_TYPE_STANDALONE if standalone else AGENT_TYPE_BOARD_WORKER,
    )
    session.add_all([org, member, gateway, board, agent])
    await session.commit()
    return OrganizationContext(organization=org, member=member), agent, board


# ── grant ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_creates_access_for_standalone_agent() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, board = await _seed(session)
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(board.id), "access_level": "write"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["agent_id"] == str(agent.id)
        assert body["board_id"] == str(board.id)
        assert body["access_level"] == "write"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_grant_is_idempotent_returns_existing_grant() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, board = await _seed(session)
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            first = await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(board.id), "access_level": "read"},
            )
            second = await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(board.id), "access_level": "read"},
            )
        assert first.status_code == 200
        assert second.status_code == 200
        # Same grant returned both times
        assert first.json()["id"] == second.json()["id"]

        async with sm() as session:
            stmt = select(AgentBoardAccess).where(AgentBoardAccess.agent_id == agent.id)
            grants = (await session.exec(stmt)).all()
        assert len(grants) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_grant_idempotent_upgrades_read_to_write() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, board = await _seed(session)
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(board.id), "access_level": "read"},
            )
            upgraded = await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(board.id), "access_level": "write"},
            )
        assert upgraded.status_code == 200
        assert upgraded.json()["access_level"] == "write"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_grant_idempotent_does_not_downgrade_write_to_read() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, board = await _seed(session)
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(board.id), "access_level": "write"},
            )
            attempt = await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(board.id), "access_level": "read"},
            )
        assert attempt.status_code == 200
        # Existing write grant stays write — no silent downgrade.
        assert attempt.json()["access_level"] == "write"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_grant_rejects_non_standalone_agent() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, board = await _seed(session, standalone=False)
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(board.id), "access_level": "read"},
            )
        assert resp.status_code == 422
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_grant_rejects_cross_org_board() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, _board = await _seed(session)
            other_org = Organization(id=uuid4(), name="other")
            other_gw = Gateway(
                id=uuid4(),
                organization_id=other_org.id,
                name="gw",
                url="https://gw.example",
                token="t",
                workspace_root="/tmp/ws",
            )
            foreign_board = Board(
                id=uuid4(),
                organization_id=other_org.id,
                name="cross",
                slug=f"cross-{uuid4()}",
                gateway_id=other_gw.id,
            )
            session.add_all([other_org, other_gw, foreign_board])
            await session.commit()
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/agents/{agent.id}/board-access",
                json={"board_id": str(foreign_board.id), "access_level": "read"},
            )
        assert resp.status_code == 404
    finally:
        await engine.dispose()


# ── revoke by board_id (idempotent) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_by_board_removes_existing_grant() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, board = await _seed(session)
            session.add(
                AgentBoardAccess(agent_id=agent.id, board_id=board.id, access_level="read"),
            )
            await session.commit()
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete(
                f"/api/v1/agents/{agent.id}/board-access",
                params={"board_id": str(board.id)},
            )
        assert resp.status_code == 200

        async with sm() as session:
            stmt = select(AgentBoardAccess).where(AgentBoardAccess.agent_id == agent.id)
            remaining = (await session.exec(stmt)).all()
        assert remaining == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_revoke_by_board_is_idempotent_when_no_grant_exists() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, board = await _seed(session)
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete(
                f"/api/v1/agents/{agent.id}/board-access",
                params={"board_id": str(board.id)},
            )
        # No grant exists, but the call still succeeds — automation can fire it
        # safely without first checking whether a grant is present.
        assert resp.status_code == 200
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_revoke_by_board_rejects_cross_org_board() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, _board = await _seed(session)
            other_org = Organization(id=uuid4(), name="other")
            other_gw = Gateway(
                id=uuid4(),
                organization_id=other_org.id,
                name="gw",
                url="https://gw.example",
                token="t",
                workspace_root="/tmp/ws",
            )
            foreign_board = Board(
                id=uuid4(),
                organization_id=other_org.id,
                name="x",
                slug=f"x-{uuid4()}",
                gateway_id=other_gw.id,
            )
            session.add_all([other_org, other_gw, foreign_board])
            session.add(
                AgentBoardAccess(
                    agent_id=agent.id,
                    board_id=foreign_board.id,
                    access_level="read",
                ),
            )
            await session.commit()
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete(
                f"/api/v1/agents/{agent.id}/board-access",
                params={"board_id": str(foreign_board.id)},
            )
        assert resp.status_code == 404
    finally:
        await engine.dispose()


# ── revoke by grant_id (existing path still works) ───────────────────────────


@pytest.mark.asyncio
async def test_revoke_by_grant_id_still_works() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            ctx, agent, board = await _seed(session)
            grant = AgentBoardAccess(agent_id=agent.id, board_id=board.id, access_level="read")
            session.add(grant)
            await session.commit()
            grant_id = grant.id
        app = _build_app(sm, org_ctx=ctx)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete(f"/api/v1/agents/{agent.id}/board-access/{grant_id}")
        assert resp.status_code == 200
    finally:
        await engine.dispose()
