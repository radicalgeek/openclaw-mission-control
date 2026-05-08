# ruff: noqa: INP001
"""Tests for POST /backlog/estimate and POST /backlog/prioritise."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
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
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
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


async def _seed(session: AsyncSession) -> tuple[User, Board, Agent, Agent]:
    org_id = uuid4()
    gw_id = uuid4()
    board_id = uuid4()
    user = User(id=uuid4(), clerk_user_id=f"cu_{uuid4()}", email=f"u{uuid4()}@x.test")
    estimator = Agent(
        id=uuid4(),
        gateway_id=gw_id,
        name="Estimator",
        agent_type=AGENT_TYPE_STANDALONE,
        openclaw_session_id="estimator-session",
        identity_profile={"role_template": "estimator"},
    )
    prioritiser = Agent(
        id=uuid4(),
        gateway_id=gw_id,
        name="Prioritiser",
        agent_type=AGENT_TYPE_STANDALONE,
        openclaw_session_id="prioritiser-session",
        identity_profile={"role_template": "priority"},
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
                objective="Ship the thing",
            ),
            user,
            estimator,
            prioritiser,
        ],
    )
    await session.commit()
    board = await session.get(Board, board_id)
    assert board is not None
    return user, board, estimator, prioritiser


def _capture_dispatch_patches() -> tuple[list[dict[str, Any]], Any, Any]:
    captured: list[dict[str, Any]] = []

    async def _fake_dispatch(self: Any, **kwargs: Any) -> None:
        captured.append(kwargs)

    async def _fake_config(self: Any, board: Board) -> tuple[Any, Any]:
        return object(), object()

    p1 = patch(
        "app.services.openclaw.planning_service.AbstractGatewayMessagingService."
        "_dispatch_gateway_message",
        _fake_dispatch,
    )
    p2 = patch(
        "app.services.openclaw.gateway_dispatch.GatewayDispatchService."
        "require_gateway_config_for_board",
        _fake_config,
    )
    return captured, p1, p2


# ── /backlog/estimate ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_estimate_dispatches_to_estimator_for_unestimated_tasks() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, estimator, _prio = await _seed(session)
            t_unestimated = Task(
                board_id=board.id, title="Need estimate", status="backlog", is_backlog=True
            )
            t_already = Task(
                board_id=board.id,
                title="Already estimated",
                status="backlog",
                is_backlog=True,
                estimate_minutes=60,
            )
            session.add_all([t_unestimated, t_already])
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture_dispatch_patches()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch("app.api.sprints.settings.org_estimator_agent_id", str(estimator.id)),
            ):
                resp = await c.post(f"/api/v1/boards/{board.id}/backlog/estimate")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dispatched"] is True
        assert body["task_count"] == 1
        assert body["skipped_existing"] == 1
        assert body["agent_session"] == "estimator-session"
        # The unestimated task ID is the one dispatched
        assert body["task_ids"] == [str(t_unestimated.id)]
        # Verify the dispatch was for the estimator session
        assert captured[0]["session_key"] == "estimator-session"
        assert "BACKLOG ESTIMATION REQUEST" in captured[0]["message"]
        assert str(t_unestimated.id) in captured[0]["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_estimate_returns_no_dispatch_when_all_tasks_already_estimated() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, estimator, _prio = await _seed(session)
            session.add(
                Task(
                    board_id=board.id,
                    title="t",
                    status="backlog",
                    is_backlog=True,
                    estimate_minutes=30,
                ),
            )
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture_dispatch_patches()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch("app.api.sprints.settings.org_estimator_agent_id", str(estimator.id)),
            ):
                resp = await c.post(f"/api/v1/boards/{board.id}/backlog/estimate")
        body = resp.json()
        assert body["dispatched"] is False
        assert body["task_count"] == 0
        assert body["skipped_existing"] == 1
        assert body["reason"] == "no_backlog_tasks_need_estimate"
        assert captured == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_estimate_force_includes_already_estimated_tasks() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, estimator, _prio = await _seed(session)
            session.add_all(
                [
                    Task(
                        board_id=board.id,
                        title="A",
                        status="backlog",
                        is_backlog=True,
                        estimate_minutes=30,
                    ),
                    Task(board_id=board.id, title="B", status="backlog", is_backlog=True),
                ],
            )
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture_dispatch_patches()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch("app.api.sprints.settings.org_estimator_agent_id", str(estimator.id)),
            ):
                resp = await c.post(
                    f"/api/v1/boards/{board.id}/backlog/estimate",
                    params={"force": "true"},
                )
        body = resp.json()
        assert body["dispatched"] is True
        assert body["task_count"] == 2
        assert body["skipped_existing"] == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_estimate_returns_unavailable_when_no_estimator_configured() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, estimator, _prio = await _seed(session)
            estimator.identity_profile = {}
            session.add(estimator)
            session.add(Task(board_id=board.id, title="t", status="backlog", is_backlog=True))
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture_dispatch_patches()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with p1, p2, patch("app.api.sprints.settings.org_estimator_agent_id", ""):
                resp = await c.post(f"/api/v1/boards/{board.id}/backlog/estimate")
        body = resp.json()
        assert body["dispatched"] is False
        assert body["reason"] == "org_estimator_agent_unavailable"
        # Tasks were identified but not dispatched
        assert body["task_count"] == 1
        assert captured == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_estimate_dispatches_by_role_template_when_env_id_empty() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, _estimator, _prio = await _seed(session)
            session.add(Task(board_id=board.id, title="t", status="backlog", is_backlog=True))
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture_dispatch_patches()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with p1, p2, patch("app.api.sprints.settings.org_estimator_agent_id", ""):
                resp = await c.post(f"/api/v1/boards/{board.id}/backlog/estimate")
        body = resp.json()
        assert body["dispatched"] is True
        assert body["agent_session"] == "estimator-session"
        assert captured[0]["session_key"] == "estimator-session"
    finally:
        await engine.dispose()


# ── /backlog/prioritise ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prioritise_dispatches_for_tasks_with_default_score() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, _est, prioritiser = await _seed(session)
            session.add_all(
                [
                    # priority_score=50 is the model default → considered un-prioritised
                    Task(
                        board_id=board.id,
                        title="default-score",
                        status="backlog",
                        is_backlog=True,
                    ),
                    Task(
                        board_id=board.id,
                        title="explicit",
                        status="backlog",
                        is_backlog=True,
                        priority_score=80,
                        priority="critical",
                    ),
                ],
            )
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture_dispatch_patches()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch("app.api.sprints.settings.org_prioritiser_agent_id", str(prioritiser.id)),
            ):
                resp = await c.post(f"/api/v1/boards/{board.id}/backlog/prioritise")
        body = resp.json()
        assert body["dispatched"] is True
        assert body["task_count"] == 1
        assert body["skipped_existing"] == 1
        assert body["agent_session"] == "prioritiser-session"
        assert "BACKLOG PRIORITISATION REQUEST" in captured[0]["message"]
        assert "Ship the thing" in captured[0]["message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_prioritise_returns_unavailable_when_no_prioritiser_configured() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, _est, prioritiser = await _seed(session)
            prioritiser.identity_profile = {}
            session.add(prioritiser)
            session.add(Task(board_id=board.id, title="t", status="backlog", is_backlog=True))
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture_dispatch_patches()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with p1, p2, patch("app.api.sprints.settings.org_prioritiser_agent_id", ""):
                resp = await c.post(f"/api/v1/boards/{board.id}/backlog/prioritise")
        body = resp.json()
        assert body["dispatched"] is False
        assert body["reason"] == "org_prioritiser_agent_unavailable"
        assert captured == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_prioritise_no_tasks_returns_no_dispatch() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, _est, prioritiser = await _seed(session)
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture_dispatch_patches()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch("app.api.sprints.settings.org_prioritiser_agent_id", str(prioritiser.id)),
            ):
                resp = await c.post(f"/api/v1/boards/{board.id}/backlog/prioritise")
        body = resp.json()
        assert body["dispatched"] is False
        assert body["task_count"] == 0
        assert body["reason"] == "no_backlog_tasks_need_priority"
    finally:
        await engine.dispose()
