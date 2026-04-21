# ruff: noqa: INP001
"""Tests for MCP proxy API endpoints (WP-MC2 / WP-MC11)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    require_user_or_agent,
)
from app.api.mcp_proxy import _rate_limit_buckets
from app.api.mcp_proxy import router as mcp_proxy_router
from app.db.session import get_session
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.services.openclaw.mcp_proxy import (
    McpResource,
    McpTool,
    McpToolContent,
    McpToolResult,
    McpToolUiMeta,
)


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_test_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(mcp_proxy_router)
    app.include_router(api_v1)

    async def _override_session() -> AsyncSession:
        async with session_maker() as session:
            yield session

    actor = ActorContext(actor_type="user")

    async def _override_actor() -> ActorContext:
        return actor

    async def _override_board(
        board_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> Board:
        board = await Board.objects.by_id(UUID(board_id)).first(session)
        if board is None:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return board

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[require_user_or_agent] = _override_actor
    app.dependency_overrides[get_board_for_actor_read] = _override_board
    app.dependency_overrides[get_board_for_actor_write] = _override_board
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
        )
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


# ---------------------------------------------------------------------------
# list_mcp_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_mcp_tools_returns_empty_list_when_no_gateway_support() -> None:
    """GET /boards/{id}/mcp/tools returns [] when gateway has no mcp support."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        board = await _seed_board(s)

    with patch("app.api.mcp_proxy.McpProxyService.list_tools", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = []
        app = _build_test_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/v1/boards/{board.id}/mcp/tools")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"tools": []}


@pytest.mark.asyncio
async def test_list_mcp_tools_returns_tool_list() -> None:
    """GET /boards/{id}/mcp/tools returns serialised tools."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        board = await _seed_board(s)

    tool = McpTool(
        name="render_chart",
        title="Render Chart",
        description="Renders a chart.",
        input_schema={"type": "object", "properties": {}},
        ui_meta=McpToolUiMeta(resource_uri="ui://mission-control/chart.html"),
        agent_id="agent-abc",
    )

    with patch("app.api.mcp_proxy.McpProxyService.list_tools", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [tool]
        app = _build_test_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/v1/boards/{board.id}/mcp/tools")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["tools"]) == 1
    t = data["tools"][0]
    assert t["name"] == "render_chart"
    assert t["agent_id"] == "agent-abc"
    assert t["ui_meta"]["resource_uri"] == "ui://mission-control/chart.html"


# ---------------------------------------------------------------------------
# call_mcp_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_mcp_tool_returns_result() -> None:
    """POST /boards/{id}/mcp/tools/call proxies to McpProxyService and returns result."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        board = await _seed_board(s)

    # Clear rate limit state for this board
    _rate_limit_buckets.clear()

    result = McpToolResult(
        content=[McpToolContent(type="text", text="ok")],
        ui_meta=McpToolUiMeta(resource_uri="ui://mission-control/chart.html"),
        resource_html="<html>chart</html>",
    )

    with patch("app.api.mcp_proxy.McpProxyService.call_tool", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = result
        app = _build_test_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/mcp/tools/call",
                json={
                    "tool_name": "render_chart",
                    "agent_id": "agent-abc",
                    "arguments": {"type": "bar"},
                },
            )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["resource_html"] == "<html>chart</html>"
    assert data["content"][0]["text"] == "ok"


@pytest.mark.asyncio
async def test_call_mcp_tool_rate_limit_exceeded() -> None:
    """POST /boards/{id}/mcp/tools/call returns 429 after exceeding rate limit."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        board = await _seed_board(s)

    import time

    board_key = str(board.id)
    # Fill the bucket with 10 fresh calls
    now = time.monotonic()
    _rate_limit_buckets[board_key] = [now - 1.0] * 10

    result = McpToolResult(content=[], ui_meta=McpToolUiMeta(), resource_html=None)
    with patch("app.api.mcp_proxy.McpProxyService.call_tool", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = result
        app = _build_test_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/mcp/tools/call",
                json={
                    "tool_name": "render_chart",
                    "agent_id": "agent-abc",
                    "arguments": {},
                },
            )

    assert resp.status_code == 429, resp.text
    _rate_limit_buckets.pop(board_key, None)


# ---------------------------------------------------------------------------
# read_mcp_resource
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_mcp_resource_returns_html() -> None:
    """GET /boards/{id}/mcp/resources returns HTML resource content."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        board = await _seed_board(s)

    resource = McpResource(
        uri="ui://mission-control/chart.html",
        mime_type="text/html",
        text="<html>chart</html>",
    )

    with patch(
        "app.api.mcp_proxy.McpProxyService.read_resource", new_callable=AsyncMock
    ) as mock_read:
        mock_read.return_value = resource
        app = _build_test_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                f"/api/v1/boards/{board.id}/mcp/resources",
                params={
                    "agent_id": "agent-abc",
                    "uri": "ui://mission-control/chart.html",
                },
            )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["text"] == "<html>chart</html>"
    assert data["mime_type"] == "text/html"
    assert data["uri"] == "ui://mission-control/chart.html"


@pytest.mark.asyncio
async def test_read_mcp_resource_404_for_unknown_board() -> None:
    """GET /boards/{id}/mcp/resources returns 404 for an unknown board ID."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = _build_test_app(sm)
    unknown_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            f"/api/v1/boards/{unknown_id}/mcp/resources",
            params={"agent_id": "agent-abc", "uri": "ui://mission-control/chart.html"},
        )
    assert resp.status_code == 404, resp.text
