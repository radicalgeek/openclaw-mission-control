# MCP Apps in Chat — Agent Chart Rendering Plan

> **Goal**: Allow agents to render rich data visualisations (burndowns, bar/pie
> charts, status breakdowns, etc.) inside every chat surface in the application,
> without requiring a separate app-framework or heavyweight protocol change.

---

## 1. Investigation Summary

### 1.1 Chat surfaces inventory

| Surface | Render component | Backing store | Uses `<Markdown>`? | Structured metadata? |
|---|---|---|---|---|
| Board chat (side-panel) | `ChatMessageCard` in `boards/[boardId]/page.tsx` | `BoardMemory` (is_chat=true) | ✅ `variant="basic"` | tags `string[]` only |
| Board-group chat (side-panel) | `GroupChatMessageCard` in `board-groups/[groupId]/page.tsx` | `BoardGroupMemory` | ✅ `variant="basic"` | tags `string[]` only |
| Channel threads | `MessageBubble` in `MessageThread.tsx` | `ThreadMessage` | ✅ `variant="comment"` | `event_metadata JSON` + `content_type` discriminator |
| Planning chat | `MessageBubble` in `PlanDetail.tsx` | `PlanMessage` (in-memory list) | ❌ raw text | role only |

All surfaces except planning already go through the shared `<Markdown>` component
(`frontend/src/components/atoms/Markdown.tsx`).

### 1.2 Existing frontend dependencies

`recharts ^3.7.0` is **already installed** — no new chart library is needed.
`react-markdown`, `remark-gfm`, `remark-breaks` are present.

### 1.3 How agents post to each surface

| Surface | Agent endpoint used |
|---|---|
| Board chat | `POST /api/v1/boards/{board_id}/memory` (is_chat tag) |
| Board-group chat | `POST /api/v1/board-groups/{group_id}/memory` |
| Channel threads | `POST /api/v1/threads/{thread_id}/messages` |
| Planning chat | `POST /api/v1/boards/{board_id}/plans/{plan_id}/chat` |

Agents already have full read access to tasks, sprints, and board activity via the
agent-scoped API, so they can compose chart data before writing to any chat surface.

### 1.4 Existing `content_type` hook (channels only)

`ThreadMessage` already has a `content_type` discriminator:
`text | webhook_event | agent_response | system_notification`.
`MessageBubble` in `MessageThread.tsx` already switches rendering logic on this
field and reads `event_metadata` for structured payloads (`webhook_event` is the
live example).

### 1.5 Gap in board / group-chat stores

`BoardMemory` and `BoardGroupMemory` have only a `tags: string[]` column.  They
have no `event_metadata` JSON column and no `content_type` discriminator.

---

## 2. Recommended Approach — Fenced `json:chart` Code Blocks

### Rationale

The lowest-friction approach that serves **all four surfaces** with zero backend
schema changes is to define a **fenced code block convention** that the `<Markdown>`
renderer parses client-side.  An agent writes a regular Markdown message containing
a JSON chart spec inside a fenced block tagged `json:chart`:

````markdown
Here is the Sprint 3 burndown:

```json:chart
{
  "type": "line",
  "title": "Sprint 3 Burndown",
  "xKey": "day",
  "yKeys": ["remaining", "ideal"],
  "xLabel": "Day",
  "yLabel": "Story Points",
  "data": [
    { "day": "Mon", "remaining": 24, "ideal": 20 },
    { "day": "Tue", "remaining": 19, "ideal": 16 },
    { "day": "Wed", "remaining": 15, "ideal": 12 },
    { "day": "Thu", "remaining": 10, "ideal":  8 },
    { "day": "Fri", "remaining":  4, "ideal":  4 }
  ]
}
```
````

The frontend intercepts the `code` element in the `MARKDOWN_CODE_COMPONENTS` map,
detects the `json:chart` language tag, parses the JSON, and renders a `<ChartBlock>`
component instead of a `<pre>` block.

**Pros**  
- Works in board chat, group chat, channel threads, and planning chat immediately  
- Zero backend changes — content stored as plain text  
- Agents only need to know the JSON schema; no new API endpoints  
- Falls back gracefully to a raw code block if JSON is invalid  
- Chart data is human-readable in raw message history  

**Cons**  
- Not queryable or indexable server-side  
- No server-side validation of chart data  

### When to add a formal `content_type: "mcp_app_result"`

Channel threads already have the right plumbing for a richer solution.
A second phase can add this once the simpler approach proves valuable.
See §5 for the phased upgrade path.

---

## 3. Chart Specification Schema

```typescript
// frontend/src/components/atoms/ChartBlock.tsx  (new file)
export type ChartType = "line" | "area" | "bar" | "pie" | "donut";

export interface ChartSpec {
  /** Discriminates which Recharts chart to render. */
  type: ChartType;
  /** Optional title rendered above the chart. */
  title?: string;
  /** Key in each data row used as the X-axis / pie label. */
  xKey?: string;
  /** One or more keys to plot as series (Y-axis). Pie uses first key as value. */
  yKeys?: string | string[];
  /** Axis labels */
  xLabel?: string;
  yLabel?: string;
  /** Row data. Values must be numbers for numeric axes. */
  data: Record<string, string | number>[];
  /** Optional override colours (Recharts DEFAULT_COLORS used if omitted). */
  colors?: string[];
  /** Chart height in px (default 260). */
  height?: number;
}
```

### Supported chart types

| `type` | Recharts component | Primary use-case |
|---|---|---|
| `line` | `<LineChart>` | Sprint burndown, cumulative flow |
| `area` | `<AreaChart>` | Velocity trend, throughput |
| `bar` | `<BarChart>` | Per-agent workload, task count by status |
| `pie` | `<PieChart>` | Status breakdown, priority split |
| `donut` | `<PieChart innerRadius>` | Same, with centre label |

---

## 4. Implementation Work Packages

### WP-1 — `ChartBlock` React Component

**File**: `frontend/src/components/atoms/ChartBlock.tsx` (new)

- Accept a validated `ChartSpec` prop  
- Switch on `type` and render the appropriate Recharts component  
- Use a `ResponsiveContainer` (`width="100%" height={spec.height ?? 260}`)  
- Render a `<CartesianGrid>`, `<XAxis>`, `<YAxis>`, `<Tooltip>`, `<Legend>` for
  Cartesian charts  
- Use an `ErrorBoundary` wrapper so a broken spec never crashes the chat pane  
- Brand colours: use `var(--accent)` as the first series colour  

**Dependencies**: recharts (already installed)

### WP-2 — `Markdown` component `json:chart` handler

**File**: `frontend/src/components/atoms/Markdown.tsx`

Extend `MARKDOWN_CODE_COMPONENTS.code`:

```tsx
// Inside the `code` renderer, before the inline/block fallthrough:
if (className === "language-json:chart") {
  try {
    const spec: ChartSpec = JSON.parse(codeText);
    return <ChartBlock spec={spec} />;
  } catch {
    // fall through to normal code block rendering
  }
}
```

This change is additive and backward-compatible.  All three `MarkdownVariant`
values share `MARKDOWN_CODE_COMPONENTS`, so the chart block appears in board
chat, group chat, channel threads, and planning chat with a single change.

### WP-3 — Planning chat Markdown upgrade

**File**: `frontend/src/components/planning/PlanDetail.tsx`

The `MessageBubble` in `PlanDetail` currently renders `msg.content` as raw
text.  Change it to:

```tsx
<Markdown content={msg.content} variant="comment" />
```

This not only enables `json:chart` blocks but also gives agents proper Markdown
formatting in planning conversations.

### WP-4 — Agent instructions update

**File**: `backend/templates/BOARD_AGENTS.md.j2`

Add a `## Reporting & Charts` section so agents know how to produce charts:

```markdown
## Reporting & Charts

To render a chart in any chat surface, post a message containing a fenced
`json:chart` code block.  The Mission Control UI will render it interactively.

Supported types: `line`, `area`, `bar`, `pie`, `donut`.

Example — sprint burndown:
​```json:chart
{
  "type": "line",
  "title": "Sprint Burndown",
  "xKey": "day",
  "yKeys": ["remaining", "ideal"],
  "data": [
    {"day": "Mon", "remaining": 24, "ideal": 20},
    ...
  ]
}
​```

All `data` values used as Y-axis values must be numbers.
```

### WP-5 — Unit tests

| Test file | What to cover |
|---|---|
| `frontend/src/__tests__/atoms/ChartBlock.test.tsx` | Renders line/bar/pie without crashing; handles invalid JSON gracefully |
| `frontend/src/__tests__/atoms/Markdown.test.tsx` | `json:chart` fenced block renders a `<ChartBlock>` not a `<pre>` |

---

## 5. Phase 2 — Formal `mcp_app_result` Content Type (channels only)

Once the fenced block approach is in production and the pattern is validated, a
second phase can formalise it for channel threads:

### Backend

1. Add `"mcp_app_result"` to the `MessageContentType` union in
   `backend/app/models/thread_message.py` and the `channels.ts` type.
2. Agents `POST /api/v1/threads/{thread_id}/messages` with:
   ```json
   {
     "content": "Here is the burndown chart.",
     "content_type": "mcp_app_result",
     "event_metadata": {
       "app": "chart",
       "spec": { "type": "line", "title": "...", "data": [...] }
     }
   }
   ```
3. No migration needed: `event_metadata` (stored as `metadata` JSON column) and
   `content_type` already exist on `ThreadMessage`.

### Frontend

In `MessageBubble` (`MessageThread.tsx`), add a branch:

```tsx
if (message.content_type === "mcp_app_result") {
  const meta = message.event_metadata ?? {};
  if (meta.app === "chart" && meta.spec) {
    return <MpcAppResultCard message={message} />;
  }
}
```

### Phase 2 scope — board/group chat

`BoardMemory` and `BoardGroupMemory` currently have no `content_type` or
`event_metadata`.  A future migration could add:

```sql
ALTER TABLE board_memory ADD COLUMN content_type VARCHAR DEFAULT 'text';
ALTER TABLE board_memory ADD COLUMN metadata JSONB;
```

This would unify all surfaces under the same structured approach.

---

## 6. Data Available for Reporting

Agents already have authenticated read access to all the data needed for useful
reports, via existing endpoints:

| Report type | Data source |
|---|---|
| Sprint burndown | `GET /api/v1/boards/{board_id}/sprints/{sprint_id}` + sprint tickets + task status history |
| Task status breakdown | `GET /api/v1/boards/{board_id}/tasks?sprint_id=...` |
| Per-agent workload | `GET /api/v1/boards/{board_id}/tasks` → group by `assigned_agent` |
| Velocity (story points per sprint) | Completed sprints + task counts |
| Activity feed heatmap | Board activity events |
| Approval queue depth | `GET /api/v1/boards/{board_id}/approvals` |

No new backend endpoints are needed for Phase 1.  Phase 2 could introduce
purpose-built analytics endpoints that aggregate server-side for efficiency.

---

## 7. Burndown Algorithm (agent-side)

A burndown for a sprint works as follows:

1. Load sprint: `GET /api/v1/boards/{board_id}/sprints/{sprint_id}`
   → get `started_at`, `completed_at`, number of sprint days.
2. Load sprint tickets: `GET /api/v1/boards/{board_id}/sprints/{sprint_id}/tickets`
   → total story count / points.
3. For each working day:
   - Count tasks that were still `open | in_progress` at end of day using
     `created_at` / status transition events from task activity.
4. Compute ideal line: linear reduce from total to 0 over sprint duration.
5. Post chart as a `json:chart` message to board chat.

---

## 8. File Change Summary

| File | Change type | Notes |
|---|---|---|
| `frontend/src/components/atoms/ChartBlock.tsx` | **New** | Core chart renderer |
| `frontend/src/components/atoms/Markdown.tsx` | **Edit** | Intercept `json:chart` code blocks |
| `frontend/src/components/planning/PlanDetail.tsx` | **Edit** | Use `<Markdown>` in planning bubbles |
| `backend/templates/BOARD_AGENTS.md.j2` | **Edit** | Add Reporting & Charts section |
| `frontend/src/__tests__/atoms/ChartBlock.test.tsx` | **New** | Tests for chart renderer |
| `frontend/src/__tests__/atoms/Markdown.test.tsx` | **Edit** | Test `json:chart` interception |

No backend model changes, migrations, or new API endpoints are needed for Phase 1.

---

## 9. Risk & Mitigations

| Risk | Mitigation |
|---|---|
| Malformed JSON from agent crashes chat pane | `try/catch` in code renderer + error boundary on `ChartBlock` |
| Agent produces very large `data` arrays | Cap at 500 rows in `ChartBlock`; emit a warning if exceeded |
| `recharts` SSR issues (Next.js App Router) | Use `dynamic(() => import(...), { ssr: false })` for `ChartBlock` |
| Planning chat regression after Markdown upgrade | Cover `PlanDetail` in vitest; agent-only messages are short text |
| Agents misuse the schema | `validate()` in `ChartBlock` with a narrow Zod/type-guard before render |

---

## 10. Acceptance Criteria

- [ ] Posting a `json:chart` block in board chat renders a Recharts chart in the UI
- [ ] Same block works in group chat, channel threads, and planning chat
- [ ] Invalid JSON falls back to a styled code block (no crash)
- [ ] An agent can produce a burndown chart by querying sprint data and posting to board chat
- [ ] `ChartBlock` is not server-rendered (dynamic import)
- [ ] Unit tests pass for `ChartBlock` and `Markdown` chart interception
- [ ] `make check` passes with no new lint or type errors
