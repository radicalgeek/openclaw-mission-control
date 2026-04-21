# ruff: noqa: INP001
"""Tests for board memory API — mcp_app_result content_type support (WP-16)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import board_memory as board_memory_module
from app.api.board_memory import router as board_memory_router
from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    require_user_or_agent,
)
from app.db.session import get_session
from app.models.board_memory import BoardMemory
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_test_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(board_memory_router)
    app.include_router(api_v1)

    async def _override_get_session() -> AsyncSession:
        async with session_maker() as session:
            yield session

    actor = ActorContext(actor_type="user")

    async def _override_actor() -> ActorContext:
        return actor

    async def _override_board_read(
        board_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> Board:
        # Load from DB — session is injected by FastAPI
        board = await Board.objects.by_id(UUID(board_id)).first(session)
        if board is None:
            from fastapi import HTTPException
            from fastapi import status as http_status

            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return board

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[require_user_or_agent] = _override_actor
    app.dependency_overrides[get_board_for_actor_read] = _override_board_read
    app.dependency_overrides[get_board_for_actor_write] = _override_board_read
    return app


async def _seed_board(session: AsyncSession) -> Board:
    org_id = uuid4()
    gw_id = uuid4()
    board_id = uuid4()
    session.add(Organization(id=org_id, name=f"org-{org_id}"))
    session.add(
        Gateway(
            id=gw_id,
            organization_id=org_id,
            name="gw",
            url="https://gw.example.local",
            workspace_root="/tmp/ws",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gw_id,
        name="Test Board",
        slug=f"test-board-{board_id}",
    )
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return board


@pytest.mark.asyncio
async def test_board_memory_create_mcp_app_result_accepted() -> None:
    """POST with content_type=mcp_app_result and valid metadata is accepted."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        board = await _seed_board(s)

    # Patch out gateway dispatch so the test doesn't require a running gateway
    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    board_memory_module._notify_chat_targets = _noop  # type: ignore[attr-defined]

    app = _build_test_app(session_maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/boards/{board.id}/memory",
            json={
                "content": "Sprint burndown chart",
                "tags": ["chat"],
                "content_type": "mcp_app_result",
                "app_metadata": {
                    "app": "chart",
                    "spec": {
                        "type": "line",
                        "title": "Burndown",
                        "xKey": "day",
                        "yKeys": ["remaining"],
                        "data": [{"day": "Mon", "remaining": 10}],
                    },
                },
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["content_type"] == "mcp_app_result"
    assert data["app_metadata"]["app"] == "chart"
    assert "spec" in data["app_metadata"]


@pytest.mark.asyncio
async def test_board_memory_create_mcp_app_result_persisted_in_db() -> None:
    """Verify content_type and metadata are persisted in the database row."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        board = await _seed_board(s)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    board_memory_module._notify_chat_targets = _noop  # type: ignore[attr-defined]

    app = _build_test_app(session_maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/boards/{board.id}/memory",
            json={
                "content": "Velocity chart",
                "tags": ["chat"],
                "content_type": "mcp_app_result",
                "app_metadata": {
                    "app": "chart",
                    "spec": {"type": "bar", "xKey": "x", "yKeys": ["y"], "data": []},
                },
            },
        )
    assert resp.status_code == 200, resp.text
    row_id = UUID(resp.json()["id"])

    async with session_maker() as s:
        row = await s.get(BoardMemory, row_id)
    assert row is not None
    assert row.content_type == "mcp_app_result"
    assert row.app_metadata is not None
    assert row.app_metadata.get("app") == "chart"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_board_memory_create_mcp_app_result_validates_missing_metadata() -> None:
    """POST with content_type=mcp_app_result but no metadata → 422."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        board = await _seed_board(s)

    app = _build_test_app(session_maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/boards/{board.id}/memory",
            json={
                "content": "Missing metadata",
                "tags": ["chat"],
                "content_type": "mcp_app_result",
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_board_memory_create_mcp_app_result_validates_missing_app_key() -> None:
    """POST with content_type=mcp_app_result but no metadata.app → 422."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        board = await _seed_board(s)

    app = _build_test_app(session_maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/boards/{board.id}/memory",
            json={
                "content": "Bad metadata",
                "tags": ["chat"],
                "content_type": "mcp_app_result",
                "app_metadata": {"spec": {}},  # missing "app"
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_board_memory_create_plain_text_default() -> None:
    """POST without content_type defaults to 'text' and is backward compatible."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        board = await _seed_board(s)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    board_memory_module._notify_chat_targets = _noop  # type: ignore[attr-defined]

    app = _build_test_app(session_maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/boards/{board.id}/memory",
            json={"content": "Plain text message", "tags": ["chat"]},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["content_type"] == "text"
    assert data["app_metadata"] is None
