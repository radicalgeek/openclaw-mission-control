# ruff: noqa: INP001
"""Tests for POST /boards/{id}/backlog/organise and auto_organise_backlog trigger."""

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
    ActorContext,
    get_board_for_actor_write,
    get_board_for_user_read,
    get_board_for_user_write,
    require_user_auth,
    require_user_or_agent,
)
from app.api.sprints import router as sprints_router
from app.core.auth import AuthContext
from app.db.session import get_session
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.sprints import Sprint
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
    app.dependency_overrides[get_board_for_actor_write] = _board_override
    app.dependency_overrides[require_user_auth] = lambda: AuthContext(actor_type="user", user=user)
    app.dependency_overrides[require_user_or_agent] = lambda: ActorContext(
        actor_type="user",
        user=user,
    )
    return app


async def _seed(
    session: AsyncSession,
    *,
    task_count: int = 0,
    auto_organise_backlog: bool = False,
    with_estimator: bool = False,
    with_prioritiser: bool = False,
) -> tuple[User, Board, Agent | None, Agent | None]:
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
                auto_organise_backlog=auto_organise_backlog,
            ),
            user,
        ]
    )
    for i in range(task_count):
        session.add(
            Task(
                id=uuid4(),
                board_id=board_id,
                title=f"Task {i}",
                status="backlog",
                is_backlog=True,
                priority_score=50,
            )
        )
    estimator: Agent | None = None
    prioritiser: Agent | None = None
    if with_estimator:
        estimator = Agent(
            id=uuid4(),
            gateway_id=gw_id,
            name="Estimator",
            agent_type=AGENT_TYPE_STANDALONE,
            openclaw_session_id="estimator-session",
        )
        session.add(estimator)
    if with_prioritiser:
        prioritiser = Agent(
            id=uuid4(),
            gateway_id=gw_id,
            name="Prioritiser",
            agent_type=AGENT_TYPE_STANDALONE,
            openclaw_session_id="prioritiser-session",
        )
        session.add(prioritiser)
    await session.commit()
    board = await session.get(Board, board_id)
    assert board is not None
    return user, board, estimator, prioritiser


def _capture_dispatch() -> tuple[list[dict[str, Any]], Any, Any]:
    """Return (captured_calls, dispatch_patch, gateway_config_patch)."""
    captured: list[dict[str, Any]] = []

    async def _fake_dispatch(self: Any, **kwargs: Any) -> None:
        captured.append(kwargs)

    async def _fake_config(self: Any, board: Board) -> tuple[Any, Any]:
        return object(), object()

    return (
        captured,
        patch(
            "app.services.openclaw.planning_service.AbstractGatewayMessagingService."
            "_dispatch_gateway_message",
            _fake_dispatch,
        ),
        patch(
            "app.services.openclaw.gateway_dispatch.GatewayDispatchService."
            "require_gateway_config_for_board",
            _fake_config,
        ),
    )


# ---------------------------------------------------------------------------
# POST /backlog/organise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_organise_empty_backlog_returns_no_dispatch() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user, board, _, _ = await _seed(session, task_count=0)
    app = _build_app(sm, user=user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/v1/boards/{board.id}/backlog/organise")
    assert resp.status_code == 200
    body = resp.json()
    assert body["estimate_dispatched"] is False
    assert body["prioritise_dispatched"] is False
    assert body["sprint_id"] is None
    assert body["reason"] == "no_tasks_need_processing"


@pytest.mark.asyncio
async def test_organise_dispatches_agents_when_configured() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user, board, estimator, prioritiser = await _seed(
            session, task_count=3, with_estimator=True, with_prioritiser=True
        )
    assert estimator is not None and prioritiser is not None
    app = _build_app(sm, user=user)
    captured, p1, p2 = _capture_dispatch()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with (
            p1,
            p2,
            patch("app.api.sprints.settings.org_estimator_agent_id", str(estimator.id)),
            patch("app.api.sprints.settings.org_prioritiser_agent_id", str(prioritiser.id)),
        ):
            resp = await c.post(f"/api/v1/boards/{board.id}/backlog/organise")
    assert resp.status_code == 200
    body = resp.json()
    assert body["estimate_dispatched"] is True
    assert body["estimate_task_count"] == 3
    assert body["prioritise_dispatched"] is True
    assert body["prioritise_task_count"] == 3
    # two dispatches: one for estimator, one for prioritiser
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_organise_no_agent_configured_returns_not_dispatched() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user, board, _, _ = await _seed(session, task_count=2)
    app = _build_app(sm, user=user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with (
            patch("app.api.sprints.settings.org_estimator_agent_id", None),
            patch("app.api.sprints.settings.org_prioritiser_agent_id", None),
        ):
            resp = await c.post(f"/api/v1/boards/{board.id}/backlog/organise")
    assert resp.status_code == 200
    body = resp.json()
    assert body["estimate_dispatched"] is False
    assert body["prioritise_dispatched"] is False


@pytest.mark.asyncio
async def test_organise_include_sprint_creates_draft_sprint() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user, board, estimator, prioritiser = await _seed(
            session, task_count=2, with_estimator=True, with_prioritiser=True
        )
    assert estimator is not None and prioritiser is not None
    app = _build_app(sm, user=user)
    captured, p1, p2 = _capture_dispatch()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with (
            p1,
            p2,
            patch("app.api.sprints.settings.org_estimator_agent_id", str(estimator.id)),
            patch("app.api.sprints.settings.org_prioritiser_agent_id", str(prioritiser.id)),
        ):
            resp = await c.post(f"/api/v1/boards/{board.id}/backlog/organise?include_sprint=true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sprint_id"] is not None
    assert body["sprint_name"] == "Sprint 1"
    assert len(body["sprint_task_ids"]) == 2

    # verify sprint was persisted
    async with sm() as session:
        sprint = await session.get(Sprint, UUID(body["sprint_id"]))
        assert sprint is not None
        assert sprint.status == "draft"


@pytest.mark.asyncio
async def test_organise_include_sprint_auto_names_sequentially() -> None:
    """Sprint name increments based on existing sprint count."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user, board, _, _ = await _seed(session, task_count=1)
        # pre-create one sprint
        session.add(
            Sprint(
                id=uuid4(),
                organization_id=board.organization_id,
                board_id=board.id,
                name="Sprint 1",
                slug="sprint-1",
                status="completed",
                position=0,
            )
        )
        await session.commit()
    app = _build_app(sm, user=user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with (
            patch("app.api.sprints.settings.org_estimator_agent_id", None),
            patch("app.api.sprints.settings.org_prioritiser_agent_id", None),
        ):
            resp = await c.post(f"/api/v1/boards/{board.id}/backlog/organise?include_sprint=true")
    assert resp.status_code == 200
    assert resp.json()["sprint_name"] == "Sprint 2"


@pytest.mark.asyncio
async def test_organise_include_sprint_empty_backlog_returns_no_sprint() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user, board, _, _ = await _seed(session, task_count=0)
    app = _build_app(sm, user=user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/v1/boards/{board.id}/backlog/organise?include_sprint=true")
    assert resp.status_code == 200
    assert resp.json()["sprint_id"] is None


# ---------------------------------------------------------------------------
# auto_organise_backlog flag on create_backlog_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_backlog_task_triggers_auto_organise() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user, board, estimator, prioritiser = await _seed(
            session, auto_organise_backlog=True, with_estimator=True, with_prioritiser=True
        )
    assert estimator is not None and prioritiser is not None
    app = _build_app(sm, user=user)
    captured, p1, p2 = _capture_dispatch()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with (
            p1,
            p2,
            patch("app.api.sprints.settings.org_estimator_agent_id", str(estimator.id)),
            patch("app.api.sprints.settings.org_prioritiser_agent_id", str(prioritiser.id)),
        ):
            resp = await c.post(
                f"/api/v1/boards/{board.id}/backlog",
                # priority_score=50 is the sentinel for "not yet prioritised"
                json={"title": "Auto ticket", "priority_score": 50},
            )
    assert resp.status_code == 201
    # agents should have been dispatched after creation (estimate + prioritise)
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_create_backlog_task_no_auto_organise_when_flag_off() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user, board, estimator, prioritiser = await _seed(
            session, auto_organise_backlog=False, with_estimator=True, with_prioritiser=True
        )
    assert estimator is not None and prioritiser is not None
    app = _build_app(sm, user=user)
    captured, p1, p2 = _capture_dispatch()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with (
            p1,
            p2,
            patch("app.api.sprints.settings.org_estimator_agent_id", str(estimator.id)),
            patch("app.api.sprints.settings.org_prioritiser_agent_id", str(prioritiser.id)),
        ):
            resp = await c.post(
                f"/api/v1/boards/{board.id}/backlog",
                json={"title": "Manual ticket"},
            )
    assert resp.status_code == 201
    assert len(captured) == 0
