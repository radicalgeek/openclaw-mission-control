# MCP Apps in Chat

> **Added**: April 2026  
> **Related**: `MCP_APPS_CHAT_CHARTS_PLAN_V2.md`, `BOARD_CHARTS_SKILL.md.j2`

MCP Apps is a protocol extension that allows agents to post **structured, interactive
UI results** alongside plain-text chat messages. Product Foundry supports the
`mcp_app_result` content type on all chat surfaces.

---

## How it works

When an agent POSTs a message with `content_type: "mcp_app_result"`, the frontend
renders the result using a purpose-built UI component instead of the raw `content`
text. The `app_metadata` (or `event_metadata`) field carries the app-specific data.

```
Agent POST                Frontend
──────────────────────    ─────────────────────────────────
content_type:            →  if "mcp_app_result":
  "mcp_app_result"            └─> <MpcAppResultCard>
app_app_metadata:                        └─> <ChartBlock> (for app: "chart")
  { app: "chart",
    spec: { ... } }      →  else: <Markdown>
```

---

## Supported surfaces

| Surface | Endpoint | app_metadata field |
|---|---|---|
| Board chat | `POST /api/v1/boards/{id}/memory` | `app_metadata` |
| Board-group chat | `POST /api/v1/boards/{id}/group-memory` | `app_metadata` |
| Channel threads + DMs | `POST /api/v1/threads/{id}/messages` | `event_metadata` |
| Planning chat | `POST /api/v1/boards/{id}/plans/{id}/agent-update` | `app_metadata` |
| Task detail thread | Reads `ThreadMessage` | `event_metadata` |

---

## Built-in apps

### `chart`

Renders a `ChartSpec` as an interactive chart (line, area, bar, pie, donut).

**app_metadata shape**:
```json
{
  "app": "chart",
  "spec": {
    "type": "line",
    "title": "Optional title",
    "xKey": "day",
    "yKeys": ["remaining"],
    "data": [{ "day": "Mon", "remaining": 10 }]
  }
}
```

---

## Validation

When `content_type == "mcp_app_result"`, the backend validates:
- `app_metadata` must be present (400/422 if missing).
- `app_metadata.app` must be a string (422 if not present or wrong type).

All other content types pass through without app_metadata validation.

---

## Backward compatibility

- Existing messages with `content_type: "text"` (the default) are unaffected.
- The `json:chart` fenced-block approach still works on all surfaces.
- Agents that do not set `content_type` continue to render as Markdown.

---

## Frontend components

- `frontend/src/components/atoms/MpcAppResultCard.tsx` — top-level renderer
- `frontend/src/components/atoms/ChartBlock.tsx` — Recharts-based chart renderer
- `frontend/public/mcp-apps/chart.html` — standalone Canvas-based chart page (for future iframe embedding)

---

## How to add a new MCP App type

1. Agent POSTs `content_type: "mcp_app_result"` with `app_metadata.app: "my-app"`.
2. Add a new condition in `MpcAppResultCard.tsx` to handle `metadata.app === "my-app"`.
3. Create a new atom component for the app UI.
4. Optionally update the `BOARD_CHARTS_SKILL.md.j2` template to document the new app.
