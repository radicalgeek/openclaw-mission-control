# MCP Apps — Gateway Protocol Extension Plan

> **Status**: Draft
> **Date**: 11 April 2026
> **Depends on**: `MCP_APPS_CHAT_CHARTS_PLAN_V2.md` (Phase 2A — built-in apps)
> **Phase**: 2B — Full MCP Apps host support via gateway protocol

---

## 0. Context

Mission Control communicates with OpenClaw agents via a WebSocket JSON-RPC
gateway (protocol version 3). Agents receive chat messages via `chat.send`,
return responses by calling the Mission Control REST API, and have files synced
into their workspace via `agents.files.set`.

The current protocol has **no concept of MCP tools or resources**. To become a
standards-compliant MCP Apps host, Mission Control needs the gateway to expose:

1. **Tool discovery** — list tools an agent has registered, including `_meta.ui`
2. **Tool execution** — call a tool and receive structured results
3. **Resource fetching** — read `ui://` resources that serve HTML App pages
4. **Event delivery** — push tool results and UI updates to the frontend

This plan covers the gateway RPC protocol additions, backend proxy layer, and
frontend generic `AppRenderer` integration needed for full MCP Apps support.

Phase 2A (see `MCP_APPS_CHAT_CHARTS_PLAN_V2.md`) delivers built-in chart apps
without any gateway changes. This plan (Phase 2B) builds on that to support
**any** MCP App through the gateway.

---

## 1. Current Gateway Protocol Summary

### 1.1 Frame format

```
Request:  { type: "req",   id: "<uuid4>", method: "<name>", params: {...} }
Response: { type: "res",   id: "<uuid4>", ok: bool, payload: {...}, error?: {...} }
Event:    { type: "event", event: "<name>", payload: {...} }
```

### 1.2 Connection flow

1. WebSocket upgrade to gateway URL
2. Gateway optionally sends `connect.challenge` event with `nonce`
3. Client sends `connect` request with protocol version, role, scopes, and
   device identity (Ed25519 signed payload)
4. Gateway responds with server version metadata

Each `openclaw_call` opens a fresh WebSocket, performs one RPC, then closes.
For streaming patterns, the `event` frame type exists but isn't used for MCP.

### 1.3 Relevant existing methods

| Method | Relevance to MCP Apps |
|---|---|
| `agents.files.set/get/list` | Resource-like pattern — files in agent workspace |
| `node.invoke` / `node.invoke.result` | Closest analogue to `tools/call` — invoke on a node, get result |
| `config.patch` (with `baseHash`) | Config registration pattern — could register MCP tool manifests |
| `browser.request` | HTTP proxy through gateway — could forward to agent MCP HTTP endpoints |
| `skills.install/update` | Skill lifecycle — MCP Apps could follow this pattern |

### 1.4 Existing events

`agent`, `chat`, `presence`, `tick`, `node.invoke.request`,
`exec.approval.requested/resolved`, etc. The event system supports server-push
patterns needed for streaming MCP App updates.

---

## 2. Proposed New Gateway RPC Methods

### 2.1 Tool discovery

#### `mcp.tools.list`

List MCP tools registered by an agent, including `_meta.ui` metadata.

**Request:**
```json
{
  "type": "req",
  "id": "<uuid>",
  "method": "mcp.tools.list",
  "params": {
    "agentId": "<agent_id>"
  }
}
```

**Response:**
```json
{
  "type": "res",
  "id": "<uuid>",
  "ok": true,
  "payload": {
    "tools": [
      {
        "name": "show_chart",
        "title": "Show Chart",
        "description": "Render an interactive chart",
        "inputSchema": {
          "type": "object",
          "properties": {
            "chartType": { "type": "string", "enum": ["line", "bar", "pie"] },
            "data": { "type": "array" }
          }
        },
        "_meta": {
          "ui": {
            "resourceUri": "ui://agent-charts/chart.html"
          }
        }
      }
    ]
  }
}
```

#### `mcp.tools.list_all`

List tools across all agents (for tool discovery in chat surfaces).

**Request:**
```json
{
  "type": "req",
  "id": "<uuid>",
  "method": "mcp.tools.list_all",
  "params": {}
}
```

**Response:** Same shape as `mcp.tools.list`, but `tools` array includes an
additional `agentId` field on each tool.

### 2.2 Tool execution

#### `mcp.tools.call`

Call an MCP tool on an agent and receive the structured result.

**Request:**
```json
{
  "type": "req",
  "id": "<uuid>",
  "method": "mcp.tools.call",
  "params": {
    "agentId": "<agent_id>",
    "name": "show_chart",
    "arguments": {
      "chartType": "line",
      "data": [
        {"day": "Mon", "value": 10},
        {"day": "Tue", "value": 15}
      ]
    }
  }
}
```

**Response:**
```json
{
  "type": "res",
  "id": "<uuid>",
  "ok": true,
  "payload": {
    "content": [
      { "type": "text", "text": "Line chart with 2 data points" }
    ],
    "_meta": {
      "ui": {
        "resourceUri": "ui://agent-charts/chart.html"
      }
    }
  }
}
```

### 2.3 Resource fetching

#### `mcp.resources.read`

Fetch an MCP resource (typically a `ui://` HTML page for rendering in an iframe).

**Request:**
```json
{
  "type": "req",
  "id": "<uuid>",
  "method": "mcp.resources.read",
  "params": {
    "agentId": "<agent_id>",
    "uri": "ui://agent-charts/chart.html"
  }
}
```

**Response:**
```json
{
  "type": "res",
  "id": "<uuid>",
  "ok": true,
  "payload": {
    "contents": [
      {
        "uri": "ui://agent-charts/chart.html",
        "mimeType": "text/html;profile=mcp-app",
        "text": "<!DOCTYPE html><html>..."
      }
    ]
  }
}
```

### 2.4 Events

#### `mcp.tool.result` (event — gateway → client)

Pushed when an agent completes an MCP tool call asynchronously.

```json
{
  "type": "event",
  "event": "mcp.tool.result",
  "payload": {
    "agentId": "<agent_id>",
    "toolName": "show_chart",
    "requestId": "<original_request_id>",
    "content": [...],
    "_meta": { "ui": { "resourceUri": "..." } }
  }
}
```

---

## 3. Backend Proxy Layer

Mission Control backend acts as a **proxy** between the frontend and the gateway
for MCP operations. This is necessary because:

1. Frontend cannot connect to the gateway WebSocket directly (auth is device-based)
2. Resource HTML must be fetched server-side and cached
3. Tool calls need audit logging and rate limiting

### 3.1 New API endpoints

#### `GET /api/v1/boards/{board_id}/mcp/tools`

Discover MCP tools available on the board's gateway agents.

- Calls `mcp.tools.list_all` via gateway RPC
- Filters to tools with `_meta.ui` (MCP Apps)
- Caches for 60s (agent tool registrations don't change frequently)
- Returns list with agent attribution

#### `POST /api/v1/boards/{board_id}/mcp/tools/call`

Execute an MCP tool on a specific agent.

```json
{
  "agent_id": "<agent_id>",
  "tool_name": "show_chart",
  "arguments": { ... }
}
```

- Calls `mcp.tools.call` via gateway RPC
- If result has `_meta.ui.resourceUri`, immediately fetches the resource
- Returns tool result + resolved HTML content
- Logs the tool call in board activity

#### `GET /api/v1/boards/{board_id}/mcp/resources`

Fetch an MCP App resource by URI.

```
GET /api/v1/boards/{board_id}/mcp/resources?uri=ui://agent-charts/chart.html&agent_id=xxx
```

- Calls `mcp.resources.read` via gateway RPC
- Returns the HTML content with appropriate headers
- Caches rendered HTML for 5 minutes (resource content is static per version)

### 3.2 New service module

**File**: `backend/app/services/openclaw/mcp_proxy.py`

```python
class McpProxyService:
    """Proxies MCP tool/resource calls through the gateway."""

    async def list_tools(self, board_id: UUID, agent_id: UUID | None) -> list[McpTool]
    async def call_tool(self, board_id: UUID, agent_id: UUID, name: str, args: dict) -> McpToolResult
    async def read_resource(self, board_id: UUID, agent_id: UUID, uri: str) -> McpResource
```

Uses `GatewayDispatchService` to resolve the correct gateway config per board,
then calls the new `mcp.*` RPC methods.

---

## 4. Frontend Integration

### 4.1 Generic `AppRenderer` Component

**File**: `frontend/src/components/atoms/McpAppRenderer.tsx`

Unlike Phase 2A's `MpcAppResultCard` (which renders built-in apps from stored
metadata), the generic renderer fetches live resources from the gateway:

```tsx
interface McpAppRendererProps {
  boardId: string;
  agentId: string;
  resourceUri: string;
  toolResult: McpToolResult;
  onToolCall?: (name: string, args: Record<string, unknown>) => Promise<McpToolResult>;
}
```

Uses `@mcp-ui/client` `AppFrame` / `AppRenderer`:
- Fetches HTML from `GET /api/v1/boards/{board_id}/mcp/resources?uri=...`
- Renders in sandboxed iframe
- Passes tool result via `postMessage`
- Handles bidirectional communication:
  - `callServerTool` → proxied through backend → gateway → agent
  - `sendMessage` → shown in chat
  - `openLink` → validated and opened
  - `updateContext` → passed to host

### 4.2 Chat surface integration

Each surface extends the Phase 2A branching:

```tsx
// Phase 2A: stored metadata
if (message.content_type === "mcp_app_result" && message.metadata) {
  if (message.metadata.resource_uri) {
    // Phase 2B: live resource from gateway
    return <McpAppRenderer
      boardId={boardId}
      agentId={message.sender_id}
      resourceUri={message.metadata.resource_uri}
      toolResult={message.metadata.tool_result}
    />;
  }
  // Phase 2A: built-in app (chart.html)
  return <MpcAppResultCard metadata={message.metadata} fallbackContent={message.content} />;
}
// Fallback: <Markdown>
```

### 4.3 Tool palette (optional)

A UI component that shows available MCP tools per board. Operators can trigger
tool calls directly from the UI (e.g., "Generate burndown chart"):

**File**: `frontend/src/components/atoms/McpToolPalette.tsx`

- Fetches `GET /api/v1/boards/{board_id}/mcp/tools`
- Shows tools with `_meta.ui` as actionable buttons
- On click, shows input form (generated from `inputSchema`)
- Submits via `POST /api/v1/boards/{board_id}/mcp/tools/call`
- Result rendered in chat via `McpAppRenderer`

---

## 5. Agent-Side: MCP Tool Registration

### 5.1 How agents register tools

For agents to expose MCP tools, the OpenClaw gateway needs to support the MCP
server-side pattern. Two approaches:

#### Option A: Agent-declared tools via workspace config

Agents declare tools in a config file in their workspace:

```json
// tools/mcp-apps.json (provisioned via agents.files.set)
{
  "tools": [
    {
      "name": "show_chart",
      "description": "Render an interactive chart",
      "inputSchema": { ... },
      "_meta": {
        "ui": {
          "resourceUri": "ui://mission-control/chart.html"
        }
      }
    }
  ],
  "resources": [
    {
      "uri": "ui://mission-control/chart.html",
      "mimeType": "text/html;profile=mcp-app",
      "source": "builtin"
    }
  ]
}
```

The gateway reads this config and responds to `mcp.tools.list` accordingly.
Tool execution is handled by the agent's session (the agent receives a
`tools/call` request and processes it within its existing context).

#### Option B: Agent registers tools dynamically via MCP SDK

Agents use the `@modelcontextprotocol/ext-apps` SDK to register tools and
resources programmatically. The gateway acts as an MCP server transport:

```typescript
// In agent code
import { registerAppTool, registerAppResource } from '@modelcontextprotocol/ext-apps/server';

registerAppTool(server, 'show_chart', {
  description: 'Render chart',
  inputSchema: { ... },
  _meta: { ui: { resourceUri: 'ui://chart/main.html' } }
}, async (args) => {
  const data = await fetchData(args);
  return { content: [{ type: 'text', text: JSON.stringify(data) }] };
});
```

**Recommendation**: Start with **Option A** (config-file approach). It works
within the existing `agents.files.set` provisioning pattern and doesn't require
OpenClaw to implement the full MCP server SDK. Option B is the long-term target.

### 5.2 Built-in tools provisioned by Mission Control

Mission Control can provision "built-in" MCP tools as part of template sync:

- **`show_chart`** — Renders chart data (backed by `chart.html`)
- **`show_dashboard`** — Sprint/board dashboard (future)
- **`show_approval_form`** — Approval workflow UI (future)

These tools use built-in HTML resources hosted by Mission Control (not
agent-served), so the gateway only needs to route the tool call.

### 5.3 Agent skill template updates

**File**: `backend/templates/BOARD_TOOLS.md.j2`

Add section describing MCP tool registration for agents:

```markdown
## MCP App Tools

You can register interactive tools that render rich UIs in Mission Control.
Declare tools in `tools/mcp-apps.json` — Mission Control will discover them
and render their UI when you return structured results.

Available built-in UIs:
- `ui://mission-control/chart.html` — Interactive chart renderer
```

---

## 6. Gateway-Side Implementation Requirements

These changes are required in the **OpenClaw gateway codebase** (not Mission
Control). This section specifies what Mission Control needs from the gateway.

### 6.1 New RPC method handlers

| Method | Gateway behaviour |
|---|---|
| `mcp.tools.list` | Read agent's `tools/mcp-apps.json` (or dynamic registry); return tool definitions |
| `mcp.tools.list_all` | Aggregate `mcp.tools.list` across all agents |
| `mcp.tools.call` | Route tool call to agent session; agent processes and returns result |
| `mcp.resources.read` | For `builtin` resources, proxy from Mission Control URL; for agent resources, read from agent workspace or agent-served endpoint |

### 6.2 Tool call routing

When `mcp.tools.call` is received:

1. Gateway looks up the agent by `agentId`
2. If tool is declared in `tools/mcp-apps.json`, gateway sends the tool call
   to the agent's active session as a special message type
3. Agent processes the tool call (e.g., fetches data, computes chart spec)
4. Agent returns the result via the session
5. Gateway wraps the result in the response frame and sends back to MC

### 6.3 Resource resolution

For `mcp.resources.read`:

- **`source: "builtin"`**: Gateway fetches from a configured URL (Mission
  Control's `/mcp-apps/chart.html`) or from a file in the agent workspace
- **`source: "agent"`**: Gateway reads content from the agent's workspace
  (a rendered HTML file the agent has written)
- **`source: "url"`**: Gateway fetches from an external URL (CSP-controlled)

### 6.4 Protocol version

These new methods should be gated behind **protocol version 4**. The gateway
should support both v3 (existing) and v4 (with MCP methods). Mission Control
negotiates the highest supported version during `connect`:

```json
{
  "minProtocol": 3,
  "maxProtocol": 4
}
```

If the gateway responds with v3, Mission Control falls back to Phase 2A
(built-in apps only). If v4, full MCP Apps support is enabled.

---

## 7. Caching & Performance

### 7.1 Resource caching

MCP App HTML resources are typically static. Cache them in Mission Control:

| Cache layer | TTL | Invalidation |
|---|---|---|
| Backend in-memory (per-board) | 5 min | Gateway event or template resync |
| Frontend `stale-while-revalidate` | 60s | React Query with `staleTime` |

### 7.2 Tool discovery caching

Tool manifests change only on agent provisioning:

| Cache layer | TTL | Invalidation |
|---|---|---|
| Backend in-memory | 60s | `agents.files.set` for `mcp-apps.json` |
| Frontend | 120s | React Query |

### 7.3 Connection overhead

Currently each `openclaw_call` opens a fresh WebSocket. For MCP tool calls
(which may be interactive), this adds latency. Options:

- **Short-term**: Accept per-call overhead (tool calls are infrequent)
- **Medium-term**: Reuse persistent connection with multiplexed requests
- **Long-term**: Gateway exposes MCP over Streamable HTTP transport, MC
  proxies directly

---

## 8. Security Considerations

### 8.1 Iframe sandboxing

All MCP App HTML renders in `<iframe sandbox="allow-scripts">`. **Disallowed**:
- `allow-same-origin` (prevents cookie/storage access)
- `allow-top-navigation` (prevents page takeover)
- `allow-popups` (unless explicitly granted via `openLink` callback)

### 8.2 CSP for built-in apps

```
Content-Security-Policy: default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'
```

Agent-served apps may request additional CSP entries via `_meta.ui.csp`.
Mission Control validates these against an allowlist.

### 8.3 Tool call authorization

- Only operators with board access can call `mcp.tools.call`
- Agent-scoped tool calls are logged in board activity
- Rate limiting: max 10 tool calls/minute per board

### 8.4 Resource content validation

- HTML resources are sanitised server-side (strip `<script src="...">` to
  external origins not in CSP allowlist)
- Maximum resource size: 2 MB
- Resources from `source: "url"` are fetched server-side (not client-side) to
  prevent SSRF against internal endpoints

---

## 9. Work Packages

### WP-G1: Gateway — `mcp.tools.list` and `mcp.tools.list_all`

**Owner**: OpenClaw gateway team
**Scope**: Read `tools/mcp-apps.json` from agent workspace; expose via new RPC methods

### WP-G2: Gateway — `mcp.tools.call`

**Owner**: OpenClaw gateway team
**Scope**: Route tool call to agent session; handle timeout and error responses

### WP-G3: Gateway — `mcp.resources.read`

**Owner**: OpenClaw gateway team
**Scope**: Resolve resource by URI; support builtin/agent/url sources

### WP-G4: Gateway — Protocol version 4 negotiation

**Owner**: OpenClaw gateway team
**Scope**: Support v3 and v4; gate mcp.* methods behind v4

### WP-MC1: Backend — `McpProxyService`

**File**: `backend/app/services/openclaw/mcp_proxy.py`
**Scope**: Proxy `mcp.*` calls through gateway RPC; caching; error handling

### WP-MC2: Backend — MCP proxy API endpoints

**File**: `backend/app/api/mcp_proxy.py`
**Scope**: `GET /boards/{id}/mcp/tools`, `POST /boards/{id}/mcp/tools/call`,
`GET /boards/{id}/mcp/resources`

### WP-MC3: Backend — Gateway RPC client update

**File**: `backend/app/services/openclaw/gateway_rpc.py`
**Scope**: Add `mcp.*` to `GATEWAY_METHODS`; update `PROTOCOL_VERSION` negotiation
to support v3 + v4

### WP-MC4: Backend — MCP tool manifest provisioning

**File**: `backend/app/services/openclaw/provisioning.py`
**Scope**: Generate and push `tools/mcp-apps.json` with built-in tool definitions
during template sync

**File**: `backend/app/services/openclaw/constants.py`
**Scope**: Add `tools/mcp-apps.json` to `DEFAULT_GATEWAY_FILES` and
`LEAD_GATEWAY_FILES`

### WP-MC5: Frontend — Install `@mcp-ui/client`

**File**: `frontend/package.json`
**Scope**: `npm install @mcp-ui/client`

### WP-MC6: Frontend — `McpAppRenderer` component

**File**: `frontend/src/components/atoms/McpAppRenderer.tsx`
**Scope**: Generic MCP App renderer using `AppFrame`; fetches resources via
proxy API; handles bidirectional postMessage communication

### WP-MC7: Frontend — Chat surface integration (Phase 2B branch)

**Files**: Same as Phase 2A WP-9 through WP-13
**Scope**: Extend `content_type` branching to detect `resource_uri` in metadata
and render `McpAppRenderer` for live gateway resources

### WP-MC8: Frontend — `McpToolPalette` component (optional)

**File**: `frontend/src/components/atoms/McpToolPalette.tsx`
**Scope**: UI for discovering and invoking MCP tools per board

### WP-MC9: Frontend — API client for MCP proxy

**File**: `frontend/src/api/mcp.ts`
**Scope**: TypeScript client for the MCP proxy endpoints

### WP-MC10: Agent templates — MCP tool config

**File**: `backend/templates/BOARD_TOOLS.md.j2`
**Scope**: Add MCP Apps section teaching agents about tool registration

### WP-MC11: Tests

| Test file | Coverage |
|---|---|
| `backend/tests/test_mcp_proxy_api.py` | Proxy endpoints; error handling; caching |
| `backend/tests/test_mcp_proxy_service.py` | Gateway RPC calls; tool resolution |
| `frontend/src/__tests__/atoms/McpAppRenderer.test.tsx` | Iframe rendering; postMessage; error states |

### WP-MC12: Documentation

**Files**:
- `docs/reference/mcp-apps.md` — Update with Phase 2B architecture
- `docs/architecture/mcp-apps-gateway.md` — Gateway protocol extension docs
- `docs/openclaw_gateway_ws.md` — Update with `mcp.*` method reference

---

## 10. Implementation Sequence

```
WP-G4 (protocol v4 negotiation)
  └─> WP-G1 (tools.list)
        └─> WP-G2 (tools.call)
              └─> WP-G3 (resources.read)

WP-MC3 (RPC client update) ─────────────┐
WP-MC4 (tool manifest provisioning) ─┐  │
WP-MC1 (McpProxyService) ────────────┤  │
  └─> WP-MC2 (API endpoints) ────────┤  │
        └─> WP-MC5 (install SDK) ────┤  │
              └─> WP-MC6 (renderer) ─┤  │
                    └─> WP-MC7 (chat surface integration)
                    └─> WP-MC8 (tool palette, optional)
                          └─> WP-MC9 (API client)
                                └─> WP-MC10 (agent templates)
                                      └─> WP-MC11 (tests)
                                            └─> WP-MC12 (docs)
```

**Critical path**: Gateway WPs (G1-G4) are prerequisites. MC backend/frontend
work can proceed in parallel using mocks, then integrate once gateway is ready.

---

## 11. Feature Flags & Rollout

### 11.1 Protocol-gated activation

MCP Apps support is automatically gated by protocol version:

```python
# In McpProxyService
async def list_tools(self, board_id: UUID) -> list[McpTool]:
    gateway = await self._resolve_gateway(board_id)
    if gateway.protocol_version < 4:
        return []  # Graceful degradation — Phase 2A still works
    return await self._rpc("mcp.tools.list_all", {}, config=gateway.config)
```

### 11.2 Frontend feature detection

```tsx
const { data: mcpTools } = useQuery({
  queryKey: ['mcp-tools', boardId],
  queryFn: () => mcpApi.listTools(boardId),
  enabled: !!boardId,
});

// McpToolPalette and McpAppRenderer only render if tools are available
```

### 11.3 Rollout phases

1. **Alpha**: Single test gateway with v4 support; MC test environment
2. **Beta**: Opt-in per-gateway via config flag
3. **GA**: Default on for all v4+ gateways

---

## 12. Acceptance Criteria

- [ ] Gateway exposes `mcp.tools.list`, `mcp.tools.call`, `mcp.resources.read`
- [ ] Protocol v4 negotiation works; v3 gateways fall back to Phase 2A
- [ ] Mission Control proxy endpoints authenticated and rate-limited
- [ ] `McpAppRenderer` fetches live HTML resource and renders in sandboxed iframe
- [ ] Bidirectional postMessage works (UI can call tools, send messages)
- [ ] Built-in chart tool discoverable via `mcp.tools.list`
- [ ] Agent-declared tools (via `tools/mcp-apps.json`) discoverable
- [ ] Resource caching reduces gateway round-trips
- [ ] All chat surfaces render MCP Apps from gateway (board, group, channels, DMs, planning, task detail)
- [ ] `make check` passes
- [ ] API client regenerated with MCP proxy types

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| OpenClaw gateway team capacity | Phase 2A delivers value without gateway changes; 2B can wait |
| Per-call WebSocket overhead | Accept short-term; plan persistent connection for medium-term |
| Agent tool call latency (session spin-up) | Use `ensure_session` before tool calls; timeout at 30s |
| Malicious HTML in agent resources | Strict iframe sandbox; CSP; server-side content size limit |
| Protocol v4 adoption across gateways | Feature detection; graceful degradation to Phase 2A |
| `tools/mcp-apps.json` schema evolution | Version the schema; validate on read |

---

## 14. Decision Log

| Decision | Rationale |
|---|---|
| Separate plan from Phase 2A | Gateway changes have different owners and timeline |
| Protocol v4 (not v3 extension) | Clean versioning; clear capability boundary |
| Config-file tool registration first | Works within existing provisioning; no gateway SDK dependency |
| Backend proxy (not direct frontend→gateway) | Auth is device-based; need audit logging; CSP enforcement |
| `mcp.*` method prefix | Clear namespace; avoids collision with existing 78 RPC methods |
| Resource caching server-side | HTML is static per version; reduces gateway load |
| Optional `McpToolPalette` | Nice to have; core value is rendering in chat, not tool discovery UI |
