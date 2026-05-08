"""MCP Apps proxy API endpoints.

Provides three endpoints per board:

- ``GET  /boards/{board_id}/mcp/tools``          — discover available MCP tools
- ``POST /boards/{board_id}/mcp/tools/call``     — execute a tool
- ``GET  /boards/{board_id}/mcp/resources``      — fetch a UI resource (HTML)

These endpoints proxy ``mcp.*`` gateway RPC calls server-side so that:
- Browser clients are isolated from device-auth gateway connections.
- Tool calls are audited and rate-limited before reaching agents.
- Resource HTML is CSP-validated and cached at the backend layer.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    require_user_or_agent,
)
from app.core.config import settings as _settings
from app.db.session import get_session
from app.schemas.mcp_proxy import (
    McpResourceResponse,
    McpToolCallRequest,
    McpToolCallResponse,
    McpToolContentSchema,
    McpToolSchema,
    McpToolsListResponse,
    McpToolUiMetaSchema,
)
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.mcp_proxy import McpProxyService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/mcp", tags=["mcp"])

SESSION_DEP = Depends(get_session)
BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
ACTOR_DEP = Depends(require_user_or_agent)

# ---------------------------------------------------------------------------
# In-process per-board tool-call rate limiter
# Configurable via MCP_RATE_LIMIT_MAX / MCP_RATE_LIMIT_WINDOW env vars.
# Set RATE_LIMIT_ENABLED=false to disable entirely.
# ---------------------------------------------------------------------------

_RATE_LIMIT_WINDOW_S = _settings.mcp_rate_limit_window
_RATE_LIMIT_MAX_CALLS = _settings.mcp_rate_limit_max
_rate_limit_buckets: dict[str, list[float]] = defaultdict(list)


def _check_tool_call_rate_limit(board_id: UUID) -> None:
    if not _settings.rate_limit_enabled:
        return
    key = str(board_id)
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_S
    calls = _rate_limit_buckets[key]
    # Evict expired timestamps
    _rate_limit_buckets[key] = [t for t in calls if t > window_start]
    if len(_rate_limit_buckets[key]) >= _RATE_LIMIT_MAX_CALLS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"MCP tool call rate limit exceeded ({_RATE_LIMIT_MAX_CALLS}/min per board).",
        )
    _rate_limit_buckets[key].append(now)


# ---------------------------------------------------------------------------
# Endpoint helpers
# ---------------------------------------------------------------------------


def _tool_schema(tool: object) -> McpToolSchema:
    """Convert a McpTool service object to the API schema."""
    from app.services.openclaw.mcp_proxy import McpTool  # avoid circular at module level

    if not isinstance(tool, McpTool):
        raise TypeError(f"Expected McpTool, got {type(tool)}")
    return McpToolSchema(
        name=tool.name,
        title=tool.title,
        description=tool.description,
        input_schema=tool.input_schema,
        ui_meta=McpToolUiMetaSchema(resource_uri=tool.ui_meta.resource_uri),
        agent_id=tool.agent_id,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/tools", response_model=McpToolsListResponse)
async def list_mcp_tools(
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> McpToolsListResponse:
    """List all MCP Apps tools available on the board's gateway agents.

    Caches results for 60 s.  Returns an empty list when the gateway does not
    support ``mcp.*`` methods (protocol v3 only).
    """
    service = McpProxyService(session)
    tools = await service.list_tools(board.id)
    return McpToolsListResponse(tools=[_tool_schema(t) for t in tools])


@router.post("/tools/call", response_model=McpToolCallResponse)
async def call_mcp_tool(
    payload: McpToolCallRequest,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> McpToolCallResponse:
    """Execute a named MCP tool on a gateway agent and return the result.

    Rate-limited to 10 calls per board per minute.  If the tool result
    includes a ``_meta.ui.resourceUri``, the resource HTML is fetched and
    returned inline as ``resourceHtml``.
    """
    _check_tool_call_rate_limit(board.id)
    service = McpProxyService(session)
    try:
        result = await service.call_tool(
            board_id=board.id,
            agent_id=payload.agent_id,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
        )
    except OpenClawGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return McpToolCallResponse(
        content=[
            McpToolContentSchema(type=c.type, text=c.text, data=c.data) for c in result.content
        ],
        ui_meta=McpToolUiMetaSchema(resource_uri=result.ui_meta.resource_uri),
        resource_html=result.resource_html,
    )


@router.get("/resources", response_model=McpResourceResponse)
async def read_mcp_resource(
    agent_id: str = Query(..., description="Agent that owns the resource"),
    uri: str = Query(..., description="Resource URI (e.g. ui://mission-control/chart.html)"),
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> McpResourceResponse:
    """Fetch an MCP App resource (typically HTML) by URI.

    Results are cached for 5 minutes.  The URI is passed verbatim to the
    gateway ``mcp.resources.read`` RPC method.
    """
    service = McpProxyService(session)
    try:
        resource = await service.read_resource(
            board_id=board.id,
            agent_id=agent_id,
            uri=uri,
        )
    except OpenClawGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return McpResourceResponse(
        uri=resource.uri,
        mime_type=resource.mime_type,
        text=resource.text,
    )
