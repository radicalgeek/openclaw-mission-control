"""Schemas for MCP proxy API payloads."""

from __future__ import annotations

from typing import Any

from sqlmodel import SQLModel


class McpToolUiMetaSchema(SQLModel):
    """UI metadata attached to an MCP tool."""

    resource_uri: str | None = None


class McpToolSchema(SQLModel):
    """A single MCP tool exposed by an agent."""

    name: str
    title: str
    description: str
    input_schema: dict[str, Any] = {}
    ui_meta: McpToolUiMetaSchema = McpToolUiMetaSchema()
    agent_id: str | None = None


class McpToolsListResponse(SQLModel):
    """Response payload for GET /boards/{id}/mcp/tools."""

    tools: list[McpToolSchema]


class McpToolCallRequest(SQLModel):
    """Request payload for POST /boards/{id}/mcp/tools/call."""

    agent_id: str
    tool_name: str
    arguments: dict[str, Any] = {}


class McpToolContentSchema(SQLModel):
    """A single content item in an MCP tool result."""

    type: str
    text: str | None = None
    data: Any = None


class McpToolCallResponse(SQLModel):
    """Response payload for POST /boards/{id}/mcp/tools/call."""

    content: list[McpToolContentSchema]
    ui_meta: McpToolUiMetaSchema = McpToolUiMetaSchema()
    resource_html: str | None = None


class McpResourceResponse(SQLModel):
    """Response payload for GET /boards/{id}/mcp/resources."""

    uri: str
    mime_type: str
    text: str
