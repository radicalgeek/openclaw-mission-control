# ruff: noqa: INP001
"""Tests for POST /boards/{id}/sprints/auto-from-backlog."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    get_board_for_user_read,
    get_board_for_user_write,
    require_user_auth,
)
from app.api.sprints import router as sprints_router
from app.core.auth import AuthContext
from app.db.session import get_session
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.sprints import Sprint, SprintTicket
from app.models.tasks import Task
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
    return app


async def _seed(session: AsyncSession) -> tuple[User, Board]:
    org_id = uuid4()
    gw_id = uuid4()
    board_id = uuid4()
    user = User(id=uuid4(), clerk_user_id=f"cu_{uuid4()}", email=f"u{uuid4()}@x.test")
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
        ],
    )
    await session.commit()
    board = await session.get(Board, board_id)
    assert board is not None
    return user, board


@pytest.mark.asyncio
async def test_auto_from_backlog_creates_sprint_with_all_tasks_sorted_by_priority() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board = await _seed(session)
            high = Task(
                board_id=board.id,
                title="High",
                status="backlog",
                is_backlog=True,
                priority_score=80,
            )
            low = Task(
                board_id=board.id,
                title="Low",
                status="backlog",
                is_backlog=True,
                priority_score=20,
            )
            mid = Task(
                board_id=board.id,
                title="Mid",
                status="backlog",
                is_backlog=True,
                priority_score=50,
            )
            session.add_all([low, high, mid])
            await session.commit()
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/sprints/auto-from-backlog",
                json={"name": "Sprint 1", "goal": "Ship", "take": "all"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["sprint"]["status"] == "draft"
        assert body["sprint"]["name"] == "Sprint 1"
        # Highest priority first
        assert body["task_ids"] == [str(high.id), str(mid.id), str(low.id)]

        async with sm() as session:
            sprint_id = UUID(body["sprint"]["id"])
            sprint = await session.get(Sprint, sprint_id)
            assert sprint is not None
            assert sprint.status == "draft"
            for task_id in [high.id, mid.id, low.id]:
                t = await session.get(Task, task_id)
                assert t is not None
                assert t.sprint_id == sprint_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_auto_from_backlog_with_take_int_takes_top_n() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board = await _seed(session)
            session.add_all(
                [
                    Task(
                        board_id=board.id,
                        title=f"T{i}",
                        status="backlog",
                        is_backlog=True,
                        priority_score=10 * (5 - i),  # T0 highest, T4 lowest
                    )
                    for i in range(5)
                ],
            )
            await session.commit()
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/sprints/auto-from-backlog",
                json={"name": "Top 2", "take": 2},
            )
        body = resp.json()
        assert resp.status_code == 200
        assert len(body["task_ids"]) == 2

        async with sm() as session:
            sprint_id = UUID(body["sprint"]["id"])
            links = (
                await session.exec(
                    SprintTicket.objects.filter_by(sprint_id=sprint_id).build()
                    if hasattr(SprintTicket.objects.filter_by(sprint_id=sprint_id), "build")
                    else __import__("sqlmodel")
                    .select(SprintTicket)
                    .where(SprintTicket.sprint_id == sprint_id)
                )
            ).all()
        assert len(links) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_auto_from_backlog_skips_tasks_already_in_a_sprint() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board = await _seed(session)
            existing_sprint = Sprint(
                organization_id=board.organization_id,
                board_id=board.id,
                name="Existing",
                slug=f"existing-{uuid4()}",
                status="draft",
                position=0,
            )
            session.add(existing_sprint)
            await session.flush()
            assigned = Task(
                board_id=board.id,
                title="Assigned",
                status="backlog",
                is_backlog=True,
                priority_score=99,
                sprint_id=existing_sprint.id,
            )
            free = Task(
                board_id=board.id,
                title="Free",
                status="backlog",
                is_backlog=True,
                priority_score=10,
            )
            session.add_all([assigned, free])
            await session.commit()
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/sprints/auto-from-backlog",
                json={"name": "New", "take": "all"},
            )
        body = resp.json()
        assert resp.status_code == 200
        # Only the unassigned task picked up
        assert body["task_ids"] == [str(free.id)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_auto_from_backlog_409_when_no_unassigned_tasks() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board = await _seed(session)
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/sprints/auto-from-backlog",
                json={"name": "Empty", "take": "all"},
            )
        assert resp.status_code == 409
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_auto_from_backlog_with_start_true_runs_lifecycle() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board = await _seed(session)
            session.add(
                Task(
                    board_id=board.id,
                    title="X",
                    status="backlog",
                    is_backlog=True,
                    priority_score=50,
                    estimate_minutes=30,
                ),
            )
            await session.commit()
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/sprints/auto-from-backlog",
                json={"name": "Start me", "take": "all", "start": True},
            )
        body = resp.json()
        assert resp.status_code == 200
        assert body["sprint"]["status"] == "active"

        async with sm() as session:
            t = (
                await session.exec(
                    __import__("sqlmodel").select(Task).where(Task.board_id == board.id)
                )
            ).first()
            assert t is not None
            assert t.status == "inbox"
            assert t.is_backlog is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_auto_from_backlog_validates_take_value() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board = await _seed(session)
            session.add(
                Task(board_id=board.id, title="t", status="backlog", is_backlog=True),
            )
            await session.commit()
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp_zero = await c.post(
                f"/api/v1/boards/{board.id}/sprints/auto-from-backlog",
                json={"name": "Z", "take": 0},
            )
            resp_neg = await c.post(
                f"/api/v1/boards/{board.id}/sprints/auto-from-backlog",
                json={"name": "N", "take": -1},
            )
            resp_garbage = await c.post(
                f"/api/v1/boards/{board.id}/sprints/auto-from-backlog",
                json={"name": "G", "take": "lots"},
            )
        assert resp_zero.status_code == 422
        assert resp_neg.status_code == 422
        assert resp_garbage.status_code == 422
    finally:
        await engine.dispose()
