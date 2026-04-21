/**
 * Hand-written API client for the MCP Apps proxy endpoints.
 * Uses the same customFetch pattern as the generated API clients.
 *
 * Endpoints:
 *   GET  /api/v1/boards/{boardId}/mcp/tools
 *   POST /api/v1/boards/{boardId}/mcp/tools/call
 *   GET  /api/v1/boards/{boardId}/mcp/resources?agent_id=...&uri=...
 */
import { customFetch } from "./mutator";

// ─── Types ───────────────────────────────────────────────────────────────────

type ApiResponse<T> = { data: T; status: number; headers: Headers };

export type McpToolUiMeta = {
  resource_uri: string | null;
};

export type McpTool = {
  name: string;
  title: string;
  description: string;
  input_schema: Record<string, unknown>;
  ui_meta: McpToolUiMeta;
  agent_id: string | null;
};

export type McpToolsListResponse = {
  tools: McpTool[];
};

export type McpToolCallRequest = {
  agent_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
};

export type McpToolContent = {
  type: string;
  text: string | null;
  data?: unknown;
};

export type McpToolCallResponse = {
  content: McpToolContent[];
  ui_meta: McpToolUiMeta;
  resource_html: string | null;
};

export type McpResourceResponse = {
  uri: string;
  mime_type: string;
  text: string;
};

// ─── API helpers ─────────────────────────────────────────────────────────────

/**
 * List all MCP Apps tools available on a board's gateway agents.
 * Returns an empty list when the gateway does not support MCP (protocol v3).
 */
export async function listMcpTools(boardId: string): Promise<McpToolsListResponse> {
  const response = await customFetch<ApiResponse<McpToolsListResponse>>(
    `/api/v1/boards/${boardId}/mcp/tools`,
    { method: "GET" },
  );
  return response.data;
}

/**
 * Execute an MCP tool on a gateway agent.
 * Returns the tool result including inline resource HTML when available.
 */
export async function callMcpTool(
  boardId: string,
  payload: McpToolCallRequest,
): Promise<McpToolCallResponse> {
  const response = await customFetch<ApiResponse<McpToolCallResponse>>(
    `/api/v1/boards/${boardId}/mcp/tools/call`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}

/**
 * Fetch an MCP App resource HTML by URI.
 */
export async function readMcpResource(
  boardId: string,
  agentId: string,
  uri: string,
): Promise<McpResourceResponse> {
  const params = new URLSearchParams({ agent_id: agentId, uri });
  const response = await customFetch<ApiResponse<McpResourceResponse>>(
    `/api/v1/boards/${boardId}/mcp/resources?${params}`,
    { method: "GET" },
  );
  return response.data;
}
