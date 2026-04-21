# ruff: noqa: INP001
"""Unit tests for McpProxyService — gateway RPC proxying and caching (WP-MC11)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.mcp_proxy import (
    McpProxyService,
    McpTool,
    McpToolUiMeta,
    _parse_tools,
    _resource_cache,
    _resource_cache_key,
    _tool_cache,
    _tool_cache_key,
)

# ---------------------------------------------------------------------------
# _parse_tools helpers
# ---------------------------------------------------------------------------


def test_parse_tools_returns_empty_for_non_dict() -> None:
    assert _parse_tools(None) == []
    assert _parse_tools([]) == []
    assert _parse_tools("bad") == []


def test_parse_tools_returns_empty_for_missing_tools_key() -> None:
    assert _parse_tools({}) == []


def test_parse_tools_parses_valid_payload() -> None:
    payload: dict[str, Any] = {
        "tools": [
            {
                "name": "render_chart",
                "title": "Render Chart",
                "description": "A chart tool.",
                "inputSchema": {"type": "object"},
                "_meta": {"ui": {"resourceUri": "ui://mission-control/chart.html"}},
                "agentId": "agent-42",
            }
        ]
    }
    tools = _parse_tools(payload)
    assert len(tools) == 1
    t = tools[0]
    assert t.name == "render_chart"
    assert t.agent_id == "agent-42"
    assert t.ui_meta.resource_uri == "ui://mission-control/chart.html"


def test_parse_tools_skips_items_without_name() -> None:
    payload: dict[str, Any] = {"tools": [{"description": "no name here"}]}
    assert _parse_tools(payload) == []


def test_parse_tools_uses_provided_agent_id_when_item_has_none() -> None:
    payload: dict[str, Any] = {"tools": [{"name": "my_tool", "inputSchema": {}}]}
    tools = _parse_tools(payload, agent_id="fallback-agent")
    assert tools[0].agent_id == "fallback-agent"


# ---------------------------------------------------------------------------
# McpTool.from_dict / to_dict round-trip
# ---------------------------------------------------------------------------


def test_mcp_tool_from_dict_round_trip() -> None:
    raw: dict[str, Any] = {
        "name": "foo",
        "title": "Foo",
        "description": "Does foo.",
        "inputSchema": {"type": "object", "properties": {}},
        "_meta": {"ui": {"resourceUri": "mcp://foo"}},
    }
    tool = McpTool.from_dict(raw, agent_id="a")
    d = tool.to_dict()
    assert d["name"] == "foo"
    assert d["_meta"]["ui"]["resourceUri"] == "mcp://foo"
    assert d["agentId"] == "a"


# ---------------------------------------------------------------------------
# McpProxyService.list_tools — caching
# ---------------------------------------------------------------------------


def _make_service() -> McpProxyService:
    """Create a service with a dummy session (not required for unit tests)."""
    return McpProxyService(session=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_tools_returns_cached_result() -> None:
    """list_tools returns cached tools without hitting the gateway."""
    board_id = uuid4()
    cache_key = _tool_cache_key(board_id)

    fake_tools = [
        McpTool(
            name="cached_tool",
            title="Cached",
            description="from cache",
            input_schema={},
            ui_meta=McpToolUiMeta(),
        )
    ]
    _tool_cache[cache_key] = type(
        "_CacheEntry",
        (),
        {"value": fake_tools, "is_fresh": lambda self: True},
    )()

    service = _make_service()
    with patch(
        "app.services.openclaw.mcp_proxy.openclaw_call", new_callable=AsyncMock
    ) as mock_call:
        result = await service.list_tools(board_id)

    mock_call.assert_not_called()
    assert result == fake_tools
    del _tool_cache[cache_key]


@pytest.mark.asyncio
async def test_list_tools_returns_empty_when_no_gateway_config() -> None:
    """list_tools returns [] when the board has no gateway."""
    board_id = uuid4()
    # Remove any stale cache
    _tool_cache.pop(_tool_cache_key(board_id), None)

    service = _make_service()
    with patch.object(service, "_gateway_config", new_callable=AsyncMock) as mock_gw:
        mock_gw.return_value = None
        result = await service.list_tools(board_id)

    assert result == []


@pytest.mark.asyncio
async def test_list_tools_returns_empty_on_unsupported_method() -> None:
    """list_tools returns [] when gateway raises 'unknown method' error."""
    board_id = uuid4()
    _tool_cache.pop(_tool_cache_key(board_id), None)

    service = _make_service()
    with (
        patch.object(service, "_gateway_config", new_callable=AsyncMock) as mock_gw,
        patch("app.services.openclaw.mcp_proxy.openclaw_call", new_callable=AsyncMock) as mock_call,
    ):
        mock_gw.return_value = object()
        mock_call.side_effect = OpenClawGatewayError("unknown method: mcp.tools.list_all")
        result = await service.list_tools(board_id)

    assert result == []


@pytest.mark.asyncio
async def test_list_tools_populates_cache_on_success() -> None:
    """list_tools stores results in the tool cache after a successful gateway call."""
    board_id = uuid4()
    _tool_cache.pop(_tool_cache_key(board_id), None)

    service = _make_service()
    gateway_payload: dict[str, Any] = {"tools": [{"name": "my_tool", "inputSchema": {}}]}
    with (
        patch.object(service, "_gateway_config", new_callable=AsyncMock) as mock_gw,
        patch("app.services.openclaw.mcp_proxy.openclaw_call", new_callable=AsyncMock) as mock_call,
    ):
        mock_gw.return_value = object()
        mock_call.return_value = gateway_payload
        result = await service.list_tools(board_id)

    assert len(result) == 1
    assert result[0].name == "my_tool"
    assert _tool_cache_key(board_id) in _tool_cache
    _tool_cache.pop(_tool_cache_key(board_id), None)


# ---------------------------------------------------------------------------
# McpProxyService.invalidate_tool_cache
# ---------------------------------------------------------------------------


def test_invalidate_tool_cache_removes_entry() -> None:
    board_id = uuid4()
    key = _tool_cache_key(board_id)
    _tool_cache[key] = object()  # type: ignore[assignment]
    service = _make_service()
    service.invalidate_tool_cache(board_id)
    assert key not in _tool_cache


# ---------------------------------------------------------------------------
# McpProxyService.read_resource — caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_resource_cached() -> None:
    """read_resource returns cached resource without hitting the gateway."""
    from app.services.openclaw.mcp_proxy import McpResource, _CacheEntry

    board_id = uuid4()
    uri = "ui://mission-control/chart.html"
    cache_key = _resource_cache_key(board_id, uri)

    fake_resource = McpResource(uri=uri, mime_type="text/html", text="<html/>")
    _resource_cache[cache_key] = _CacheEntry(value=fake_resource, expires_at=time.monotonic() + 300)

    service = _make_service()
    with patch(
        "app.services.openclaw.mcp_proxy.openclaw_call", new_callable=AsyncMock
    ) as mock_call:
        result = await service.read_resource(board_id, "agent-x", uri)

    mock_call.assert_not_called()
    assert result.text == "<html/>"
    del _resource_cache[cache_key]


@pytest.mark.asyncio
async def test_read_resource_raises_when_no_gateway() -> None:
    """read_resource raises OpenClawGatewayError when board has no gateway."""
    board_id = uuid4()
    uri = "ui://test"
    _resource_cache.pop(_resource_cache_key(board_id, uri), None)

    service = _make_service()
    with patch.object(service, "_gateway_config", new_callable=AsyncMock) as mock_gw:
        mock_gw.return_value = None
        with pytest.raises(OpenClawGatewayError, match="No gateway configured"):
            await service.read_resource(board_id, "agent-x", uri)


# ---------------------------------------------------------------------------
# McpProxyService.call_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_returns_result_without_resource_html_when_no_uri() -> None:
    """call_tool returns a result with resource_html=None when no resourceUri in _meta."""
    board_id = uuid4()
    service = _make_service()

    gateway_payload: dict[str, Any] = {
        "content": [{"type": "text", "text": "done"}],
        "_meta": {},
    }
    with (
        patch.object(service, "_gateway_config", new_callable=AsyncMock) as mock_gw,
        patch("app.services.openclaw.mcp_proxy.openclaw_call", new_callable=AsyncMock) as mock_call,
    ):
        mock_gw.return_value = object()
        mock_call.return_value = gateway_payload
        result = await service.call_tool(board_id, "agent-x", "my_tool", {})

    assert len(result.content) == 1
    assert result.content[0].text == "done"
    assert result.resource_html is None


@pytest.mark.asyncio
async def test_call_tool_fetches_resource_html_when_uri_present() -> None:
    """call_tool fetches the resource HTML when _meta.ui.resourceUri is set."""
    from app.services.openclaw.mcp_proxy import McpResource

    board_id = uuid4()
    service = _make_service()

    gateway_payload: dict[str, Any] = {
        "content": [{"type": "text", "text": "rendered"}],
        "_meta": {"ui": {"resourceUri": "ui://mission-control/chart.html"}},
    }
    fake_resource = McpResource(
        uri="ui://mission-control/chart.html",
        mime_type="text/html",
        text="<html>chart</html>",
    )

    with (
        patch.object(service, "_gateway_config", new_callable=AsyncMock) as mock_gw,
        patch("app.services.openclaw.mcp_proxy.openclaw_call", new_callable=AsyncMock) as mock_call,
        patch.object(service, "read_resource", new_callable=AsyncMock) as mock_read,
    ):
        mock_gw.return_value = object()
        mock_call.return_value = gateway_payload
        mock_read.return_value = fake_resource
        result = await service.call_tool(board_id, "agent-x", "render_chart", {})

    assert result.resource_html == "<html>chart</html>"


@pytest.mark.asyncio
async def test_call_tool_handles_resource_fetch_failure_gracefully() -> None:
    """call_tool continues without resource_html if read_resource raises."""
    board_id = uuid4()
    service = _make_service()

    gateway_payload: dict[str, Any] = {
        "content": [],
        "_meta": {"ui": {"resourceUri": "ui://fail"}},
    }

    with (
        patch.object(service, "_gateway_config", new_callable=AsyncMock) as mock_gw,
        patch("app.services.openclaw.mcp_proxy.openclaw_call", new_callable=AsyncMock) as mock_call,
        patch.object(service, "read_resource", new_callable=AsyncMock) as mock_read,
    ):
        mock_gw.return_value = object()
        mock_call.return_value = gateway_payload
        mock_read.side_effect = OpenClawGatewayError("resource not found")
        result = await service.call_tool(board_id, "agent-x", "bad_tool", {})

    assert result.resource_html is None
