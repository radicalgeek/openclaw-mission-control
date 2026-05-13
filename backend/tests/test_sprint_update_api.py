# ruff: noqa: INP001
"""Tests for PATCH /boards/{id}/sprints/{id}."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    ActorContext,
    get_board_for_user_read,
    get_board_for_user_write,
    require_user_auth,
    require_user_or_agent,
)
from app.api.sprints import router as sprints_router
from app.core.auth import AuthContext
from app.core.time import utcnow
from app.db.session import get_session
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.sprints import Sprint
from app.models.users import User


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_app(session_maker: async_sessionmaker[AsyncSession], *, user: User) -> FastAPI:
    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(sprints_router)
    app.include_router(api)

    async def _session_override():
        async with session_maker() as s:
            yield s

    async def _board_override(
        board_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> Board:
        from fastapi import HTTPException
        from fastapi import status as http_status

        board = await Board.objects.by_id(UUID(board_id)).first(session)
        if board is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return board

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_board_for_user_read] = _board_override
    app.dependency_overrides[get_board_for_user_write] = _board_override
    app.dependency_overrides[require_user_auth] = lambda: AuthContext(actor_type="user", user=user)
    app.dependency_overrides[require_user_or_agent] = lambda: ActorContext(
        actor_type="user",
        user=user,
    )
    return app


async def _seed(session: AsyncSession) -> tuple[User, Board, Sprint]:
    org_id = uuid4()
    gw_id = uuid4()
    board_id = uuid4()
    user = User(id=uuid4(), clerk_user_id=f"cu_{uuid4()}", email=f"u{uuid4()}@x.test")
    sprint = Sprint(
        organization_id=org_id,
        board_id=board_id,
        name="Draft Sprint 1",
        slug="draft-sprint-1",
        status="completed",
        completed_at=utcnow(),
    )
    session.add_all(
        [
            Organization(id=org_id, name=f"org-{org_id}"),
            Gateway(
                id=gw_id,
                organization_id=org_id,
                name="gw",
                url="https://gw.example",
                token="t",
                workspace_root="/tmp/ws",
            ),
            Board(
                id=board_id,
                organization_id=org_id,
                gateway_id=gw_id,
                name="b",
                slug=f"b-{uuid4()}",
            ),
            user,
            sprint,
        ],
    )
    await session.commit()
    board = await session.get(Board, board_id)
    saved_sprint = await session.get(Sprint, sprint.id)
    assert board is not None
    assert saved_sprint is not None
    return user, board, saved_sprint


@pytest.mark.asyncio
async def test_completed_sprint_can_be_renamed() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, sprint = await _seed(session)

        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch(
                f"/api/v1/boards/{board.id}/sprints/{sprint.id}",
                json={"name": "Production Graduation Sprint"},
            )

        assert resp.status_code == 200
        assert resp.json()["name"] == "Production Graduation Sprint"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_completed_sprint_rejects_non_name_edits() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, sprint = await _seed(session)

        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch(
                f"/api/v1/boards/{board.id}/sprints/{sprint.id}",
                json={"goal": "Change the historical record"},
            )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Completed or cancelled sprints can only be renamed."
    finally:
        await engine.dispose()
