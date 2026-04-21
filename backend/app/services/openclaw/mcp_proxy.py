"""MCP Apps proxy service — gateway RPC calls for tool discovery, execution, and resource fetch.

This module proxies ``mcp.*`` gateway RPC calls on behalf of the Mission Control backend.
The backend sits between the browser client and the gateway because:

- Gateway auth is device-based (Ed25519) and cannot be called directly from the browser.
- Tool calls need audit logging and rate limiting before reaching the agent.
- Resource HTML is fetched server-side to enforce CSP/size limits.

Caching is in-process (per-worker) with TTLs matching the plan:
- Tool manifests: 60 s (invalidated when agents.files.set pushes mcp-apps.json)
- Resource HTML: 300 s (static per version; cheaper to re-fetch than maintain invalidation)

Gateway MCP support is detected via a ``mcp.tools.list`` probe on the first call per board.
When the gateway does not support ``mcp.*`` methods (v3-only), all calls return empty results
rather than raising errors — preserving Phase 2A built-in app behaviour.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

from app.core.logging import get_logger
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_rpc import GatewayConfig, OpenClawGatewayError, openclaw_call

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Cache TTLs (seconds)
# ---------------------------------------------------------------------------
_TOOL_CACHE_TTL = 60
_RESOURCE_CACHE_TTL = 300

# ---------------------------------------------------------------------------
# Typed result containers
# ---------------------------------------------------------------------------


@dataclass
class McpToolUiMeta:
    resource_uri: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "McpToolUiMeta":
        ui = d.get("ui") if isinstance(d, dict) else {}
        if not isinstance(ui, dict):
            ui = {}
        return cls(resource_uri=ui.get("resourceUri"))


@dataclass
class McpTool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    ui_meta: McpToolUiMeta
    agent_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, agent_id: str | None = None) -> "McpTool":
        meta_raw = d.get("_meta") or {}
        return cls(
            name=d.get("name", ""),
            title=d.get("title") or d.get("name", ""),
            description=d.get("description", ""),
            input_schema=d.get("inputSchema") or {},
            ui_meta=McpToolUiMeta.from_dict(meta_raw),
            agent_id=agent_id,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "_meta": {"ui": {"resourceUri": self.ui_meta.resource_uri}},
        }
        if self.agent_id is not None:
            d["agentId"] = self.agent_id
        return d


@dataclass
class McpToolContent:
    type: str
    text: str | None = None
    data: Any = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "McpToolContent":
        return cls(
            type=d.get("type", "text"),
            text=d.get("text"),
            data=d.get("data"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.text is not None:
            out["text"] = self.text
        if self.data is not None:
            out["data"] = self.data
        return out


@dataclass
class McpToolResult:
    content: list[McpToolContent]
    ui_meta: McpToolUiMeta
    resource_html: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": [c.to_dict() for c in self.content],
            "_meta": {"ui": {"resourceUri": self.ui_meta.resource_uri}},
            "resourceHtml": self.resource_html,
        }


@dataclass
class McpResource:
    uri: str
    mime_type: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "mimeType": self.mime_type,
            "text": self.text,
        }


# ---------------------------------------------------------------------------
# In-process cache entry
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float = field(default=0.0)

    def is_fresh(self) -> bool:
        return time.monotonic() < self.expires_at


# Module-level caches (keyed by board_id string)
_tool_cache: dict[str, _CacheEntry] = {}
_resource_cache: dict[str, _CacheEntry] = {}


def _tool_cache_key(board_id: UUID) -> str:
    return str(board_id)


def _resource_cache_key(board_id: UUID, uri: str) -> str:
    return f"{board_id}::{uri}"


# ---------------------------------------------------------------------------
# Helper: parse tool list payload
# ---------------------------------------------------------------------------


def _parse_tools(payload: object, *, agent_id: str | None = None) -> list[McpTool]:
    if not isinstance(payload, dict):
        return []
    tools_raw = payload.get("tools")
    if not isinstance(tools_raw, list):
        return []
    results: list[McpTool] = []
    for item in tools_raw:
        if not isinstance(item, dict):
            continue
        # agent_id may be embedded in each item (list_all) or passed as arg (list)
        effective_agent_id = item.get("agentId") or agent_id
        tool = McpTool.from_dict(item, agent_id=effective_agent_id)
        if tool.name:
            results.append(tool)
    return results


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class McpProxyService(OpenClawDBService):
    """Proxy MCP tool/resource calls through the OpenClaw gateway RPC surface."""

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    async def list_tools(self, board_id: UUID) -> list[McpTool]:
        """Return all MCP tools for the board's gateway agents.

        Results are cached for ``_TOOL_CACHE_TTL`` seconds.  An empty list is
        returned when the gateway does not support ``mcp.*`` methods.
        """
        cache_key = _tool_cache_key(board_id)
        entry = _tool_cache.get(cache_key)
        if entry is not None and entry.is_fresh():
            return cast(list[McpTool], entry.value)

        config = await self._gateway_config(board_id)
        if config is None:
            return []

        try:
            payload = await openclaw_call("mcp.tools.list_all", {}, config=config)
        except OpenClawGatewayError as exc:
            msg = str(exc).lower()
            if "unknown method" in msg or "not supported" in msg or "not found" in msg:
                logger.debug("mcp_proxy.list_tools.unsupported board_id=%s error=%s", board_id, exc)
                return []
            logger.warning("mcp_proxy.list_tools.error board_id=%s error=%s", board_id, exc)
            return []

        tools = _parse_tools(payload)
        _tool_cache[cache_key] = _CacheEntry(
            value=tools, expires_at=time.monotonic() + _TOOL_CACHE_TTL
        )
        return tools

    def invalidate_tool_cache(self, board_id: UUID) -> None:
        """Evict the cached tool manifest for a board (call after agents.files.set)."""
        _tool_cache.pop(_tool_cache_key(board_id), None)

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def call_tool(
        self,
        board_id: UUID,
        agent_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpToolResult:
        """Execute an MCP tool on a gateway agent and return the structured result.

        If the result includes a ``_meta.ui.resourceUri``, the resource HTML is
        fetched immediately and embedded in the returned ``McpToolResult``.
        """
        config = await self._gateway_config(board_id)
        if config is None:
            raise OpenClawGatewayError("No gateway configured for board")

        payload = await openclaw_call(
            "mcp.tools.call",
            {"agentId": agent_id, "name": tool_name, "arguments": arguments},
            config=config,
        )

        if not isinstance(payload, dict):
            return McpToolResult(content=[], ui_meta=McpToolUiMeta())

        content = [
            McpToolContent.from_dict(c)
            for c in (payload.get("content") or [])
            if isinstance(c, dict)
        ]
        meta_raw = payload.get("_meta") or {}
        ui_meta = McpToolUiMeta.from_dict(meta_raw)

        resource_html: str | None = None
        if ui_meta.resource_uri:
            try:
                resource = await self.read_resource(
                    board_id=board_id,
                    agent_id=agent_id,
                    uri=ui_meta.resource_uri,
                )
                resource_html = resource.text
            except OpenClawGatewayError as exc:
                logger.warning(
                    "mcp_proxy.call_tool.resource_fetch_failed tool=%s uri=%s error=%s",
                    tool_name,
                    ui_meta.resource_uri,
                    exc,
                )

        return McpToolResult(content=content, ui_meta=ui_meta, resource_html=resource_html)

    # ------------------------------------------------------------------
    # Resource fetching
    # ------------------------------------------------------------------

    async def read_resource(
        self,
        board_id: UUID,
        agent_id: str,
        uri: str,
    ) -> McpResource:
        """Fetch an MCP App resource (typically HTML) by URI."""
        cache_key = _resource_cache_key(board_id, uri)
        entry = _resource_cache.get(cache_key)
        if entry is not None and entry.is_fresh():
            return cast(McpResource, entry.value)

        config = await self._gateway_config(board_id)
        if config is None:
            raise OpenClawGatewayError("No gateway configured for board")

        payload = await openclaw_call(
            "mcp.resources.read",
            {"agentId": agent_id, "uri": uri},
            config=config,
        )

        if not isinstance(payload, dict):
            raise OpenClawGatewayError("mcp.resources.read returned invalid payload")

        contents = payload.get("contents")
        if not isinstance(contents, list) or not contents:
            raise OpenClawGatewayError("mcp.resources.read returned empty contents")

        first = contents[0]
        if not isinstance(first, dict):
            raise OpenClawGatewayError("mcp.resources.read returned malformed content item")

        resource = McpResource(
            uri=first.get("uri", uri),
            mime_type=first.get("mimeType", "text/html"),
            text=first.get("text", ""),
        )
        _resource_cache[cache_key] = _CacheEntry(
            value=resource,
            expires_at=time.monotonic() + _RESOURCE_CACHE_TTL,
        )
        return resource

    def invalidate_resource_cache(self, board_id: UUID, uri: str | None = None) -> None:
        """Evict cached resource(s) for a board."""
        if uri is not None:
            _resource_cache.pop(_resource_cache_key(board_id, uri), None)
        else:
            prefix = f"{board_id}::"
            to_delete = [k for k in _resource_cache if k.startswith(prefix)]
            for k in to_delete:
                del _resource_cache[k]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _gateway_config(self, board_id: UUID) -> GatewayConfig | None:
        from app.models.boards import Board
        from app.services.openclaw.gateway_dispatch import GatewayDispatchService

        board = await Board.objects.by_id(board_id).first(self.session)
        if board is None:
            return None
        dispatch = GatewayDispatchService(self.session)
        return await dispatch.optional_gateway_config_for_board(board)
