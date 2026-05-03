# ruff: noqa: INP001
"""Tests for POST /boards/{id}/plans/{id}/commit-tickets."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    get_board_for_user_read,
    get_board_for_user_write,
    require_user_auth,
)
from app.api.plans import router as plans_router
from app.core.auth import AuthContext
from app.db.session import get_session
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.plans import Plan
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
    api.include_router(plans_router)
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


async def _seed(
    session: AsyncSession,
    *,
    decomposed_tickets: list[dict[str, object]] | None = None,
) -> tuple[User, Board, Plan]:
    org_id = uuid4()
    gw_id = uuid4()
    board_id = uuid4()
    plan_id = uuid4()
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
                id=board_id, organization_id=org_id, gateway_id=gw_id, name="b", slug=f"b-{uuid4()}"
            ),
            user,
            Plan(
                id=plan_id,
                board_id=board_id,
                title="Graduation",
                slug=f"graduation-{uuid4()}",
                content="some plan content",
                status="active",
                decomposed_tickets=decomposed_tickets,
            ),
        ],
    )
    await session.commit()
    plan = await session.get(Plan, plan_id)
    board = await session.get(Board, board_id)
    assert plan is not None
    assert board is not None
    return user, board, plan


@pytest.mark.asyncio
async def test_commit_tickets_creates_backlog_tasks_with_plan_id() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, plan = await _seed(
                session,
                decomposed_tickets=[
                    {
                        "title": "Set up production ADO repo",
                        "description": "Create the new repo and push base.",
                        "priority": "high",
                        "estimate_minutes": 60,
                    },
                    {
                        "title": "Wire CI pipeline",
                        "description": "",
                        "priority": "medium",
                    },
                ],
            )
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/plans/{plan.id}/commit-tickets",
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["count"] == 2
        assert body["plan_id"] == str(plan.id)
        assert len(body["task_ids"]) == 2

        async with sm() as session:
            tasks = (await session.exec(select(Task).where(Task.plan_id == plan.id))).all()
        assert len(tasks) == 2
        for t in tasks:
            assert t.is_backlog is True
            assert t.status == "backlog"
            assert t.plan_id == plan.id
            assert t.auto_created is True
            assert t.auto_reason == "committed_from_plan"
        titles = {t.title for t in tasks}
        assert titles == {"Set up production ADO repo", "Wire CI pipeline"}
        # Priority score derived from label when not supplied
        for t in tasks:
            if t.title == "Wire CI pipeline":
                assert t.priority == "medium"
                assert t.priority_score == 35
            elif t.title == "Set up production ADO repo":
                assert t.priority == "high"
                assert t.priority_score == 65
                assert t.estimate_minutes == 60
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_tickets_returns_409_when_no_decomposed_tickets() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, plan = await _seed(session, decomposed_tickets=None)
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/plans/{plan.id}/commit-tickets",
            )
        assert resp.status_code == 409
        assert "no decomposed tickets" in resp.json()["detail"].lower()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_tickets_is_not_idempotent_returns_409_on_re_commit() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, plan = await _seed(
                session,
                decomposed_tickets=[{"title": "T1", "priority": "low"}],
            )
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            first = await c.post(
                f"/api/v1/boards/{board.id}/plans/{plan.id}/commit-tickets",
            )
            second = await c.post(
                f"/api/v1/boards/{board.id}/plans/{plan.id}/commit-tickets",
            )
        assert first.status_code == 201
        assert second.status_code == 409
        assert "already been committed" in second.json()["detail"]

        async with sm() as session:
            tasks = (await session.exec(select(Task).where(Task.plan_id == plan.id))).all()
        assert len(tasks) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_tickets_skips_entries_without_a_title() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, plan = await _seed(
                session,
                decomposed_tickets=[
                    {"title": "  ", "priority": "low"},  # whitespace-only — skipped
                    {"title": "Real ticket", "priority": "medium"},
                ],
            )
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/plans/{plan.id}/commit-tickets",
            )
        assert resp.status_code == 201
        assert resp.json()["count"] == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_tickets_returns_409_when_only_empty_titles() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, plan = await _seed(
                session,
                decomposed_tickets=[
                    {"title": "", "priority": "low"},
                    {"title": "   ", "priority": "low"},
                ],
            )
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/plans/{plan.id}/commit-tickets",
            )
        assert resp.status_code == 409
        assert "no usable entries" in resp.json()["detail"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_tickets_advances_plan_status_to_active() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, plan = await _seed(
                session,
                decomposed_tickets=[{"title": "T1", "priority": "low"}],
            )
            # Force draft state to verify the endpoint advances it.
            plan.status = "draft"
            session.add(plan)
            await session.commit()
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/plans/{plan.id}/commit-tickets",
            )
        assert resp.status_code == 201

        async with sm() as session:
            refreshed = await session.get(Plan, plan.id)
        assert refreshed is not None
        assert refreshed.status == "active"
    finally:
        await engine.dispose()
