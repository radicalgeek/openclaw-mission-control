# Backlog & Sprint Management — Implementation Plan

> **Status**: Draft  
> **Date**: 2026-03-31  
> **Scope**: New backlog view, sprint lifecycle, board integration, webhook on completion, API,  
>            plan-to-tickets breakdown via lead agent

---

## 1. Overview

Mission Control currently has a **Board** with four columns (Inbox → In Progress → Review → Done).
Tickets accumulate in Done indefinitely, and there is no way to pre-plan work before
pushing it to the board. This plan adds:

| Concept | Purpose |
|---------|---------|
| **Backlog** | A per-board ordered list of tickets that are *not yet* on the Kanban board. |
| **Sprint** | A time-boxed (or goal-boxed) grouping of backlog tickets. Only one sprint per board can be *active* at a time. |
| **Sprint lifecycle** | Start → all tickets land in Inbox → work proceeds on the board → when every sprint ticket reaches Done the sprint auto-completes → done tickets are archived off the board → optionally the next sprint auto-starts ("flow mode"). |
| **Completion webhook** | An outbound HTTP POST fired when a sprint finishes, enabling external integrations (CI/CD, reporting, notifications). |
| **Plan → Tickets** | A new action on the planning page that asks the board lead agent to decompose a plan into discrete backlog tickets ready for sprint assignment. |

### Design principles

1. **Non-destructive** — the existing Board page, task model, and API routes are unchanged.  
   New columns/tables are additive; new routes live under a new `/sprints` prefix.
2. **Incremental** — each work-package can be merged and tested independently.
3. **API-first** — every user-facing action is available through authenticated REST endpoints
   with the same org/board scoping and RBAC used elsewhere.

---

## 2. Data Model

### 2.1 New table: `sprints`

```
Table: sprints
─────────────────────────────────────────────────────
id                  UUID        PK, default uuid4
board_id            UUID        FK → boards.id, NOT NULL, indexed
name                str         NOT NULL
slug                str         NOT NULL, indexed
goal                str | None  Sprint objective / description
position            int         NOT NULL, default 0  (ordering in backlog)
status              str         NOT NULL, default "draft"
                                  enum: draft | queued | active | completed | cancelled
started_at          datetime | None
completed_at        datetime | None
created_by_user_id  UUID | None FK → users.id
created_at          datetime    server_default now()
updated_at          datetime    server_default now(), onupdate now()
organization_id     UUID        FK → organizations.id  (TenantScoped)
```

**Indexes**: `(board_id, status)`, `(board_id, position)`.  
**Constraint**: At most one sprint per board may have `status = 'active'`  
(enforced via partial unique index: `UNIQUE (board_id) WHERE status = 'active'`).

### 2.2 New table: `sprint_tickets`

Links backlog tickets to a sprint. A ticket belongs to **at most one sprint** (but can exist
in the backlog with `sprint_id IS NULL`).

```
Table: sprint_tickets
─────────────────────────────────────────────────────
id                  UUID        PK, default uuid4
sprint_id           UUID        FK → sprints.id, NOT NULL, indexed
task_id             UUID        FK → tasks.id, NOT NULL, indexed
position            int         NOT NULL, default 0
created_at          datetime    server_default now()
```

**Constraint**: `UNIQUE (task_id)` — a task can only be in one sprint at a time.

### 2.3 New table: `sprint_webhooks`

Configures outbound webhooks fired on sprint lifecycle events.

```
Table: sprint_webhooks
─────────────────────────────────────────────────────
id                  UUID        PK, default uuid4
board_id            UUID        FK → boards.id, NOT NULL, indexed
url                 str         NOT NULL  (target URL)
secret              str         NOT NULL  (HMAC signing secret, auto-generated)
events              list[str]   JSON, default ["sprint_completed"]
                                  possible: sprint_started, sprint_completed, sprint_cancelled
enabled             bool        NOT NULL, default True
created_at          datetime    server_default now()
updated_at          datetime    server_default now(), onupdate now()
organization_id     UUID        FK → organizations.id  (TenantScoped)
```

### 2.4 New columns on `boards`

```sql
ALTER TABLE boards ADD COLUMN auto_advance_sprint  BOOLEAN NOT NULL DEFAULT FALSE;
-- When true ("flow mode"), the next queued sprint is auto-started when the current one completes.
```

### 2.5 New column on `tasks`

```sql
ALTER TABLE tasks ADD COLUMN is_backlog  BOOLEAN NOT NULL DEFAULT FALSE;
-- True while the task lives in the backlog and has not yet been pushed to the board.
-- When a sprint starts, the flag is flipped to False and status set to "inbox".

ALTER TABLE tasks ADD COLUMN sprint_id  UUID REFERENCES sprints(id) ON DELETE SET NULL;
-- Nullable. Set when the task is assigned to a sprint.
```

### 2.6 Task status flow (unchanged)

```
backlog (is_backlog=True)
    │
    ▼  sprint starts
  inbox ──► in_progress ──► review ──► done
                                         │
                                         ▼  sprint completes
                                     (archived off board — see §4.4)
```

Tasks created from the backlog UI are created with `is_backlog = True` and `status = 'inbox'`.
They are invisible to the existing board snapshot query (which filters `is_backlog = False`).
When a sprint starts, `is_backlog` is flipped to `False` and the task appears in the Inbox column.

### 2.7 Entity-Relationship Diagram

```
boards 1──* sprints 1──* sprint_tickets *──1 tasks
boards 1──* sprint_webhooks
boards 1──1 auto_advance_sprint (column)
tasks  *──1 sprints (via tasks.sprint_id)
```

---

## 3. API Design

All routes scoped under the existing board context.  
Auth: same `get_current_user` + org membership + board access checks.

### 3.1 Sprint CRUD

| Method | Path | Body / Params | Response | Notes |
|--------|------|---------------|----------|-------|
| `GET` | `/boards/{board_id}/sprints` | `?status=draft,queued,active,completed` | `list[SprintRead]` | Ordered by `position` |
| `POST` | `/boards/{board_id}/sprints` | `SprintCreate` | `SprintRead` | Creates in `draft` status |
| `GET` | `/boards/{board_id}/sprints/{sprint_id}` | — | `SprintRead` (with ticket list) | |
| `PATCH` | `/boards/{board_id}/sprints/{sprint_id}` | `SprintUpdate` | `SprintRead` | Update name/goal/position |
| `DELETE` | `/boards/{board_id}/sprints/{sprint_id}` | — | `204` | Only allowed for `draft`/`queued` sprints |

### 3.2 Sprint Lifecycle

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| `POST` | `.../sprints/{sprint_id}/start` | — | `SprintRead` | Validates no other active sprint; moves `draft`/`queued` → `active`; pushes tickets to Inbox |
| `POST` | `.../sprints/{sprint_id}/complete` | — | `SprintRead` | Manual completion; archives done tickets; fires webhook; optionally auto-starts next sprint |
| `POST` | `.../sprints/{sprint_id}/cancel` | — | `SprintRead` | Moves `active`/`queued` → `cancelled`; returns unfinished tickets to backlog |

### 3.3 Sprint Ticket Management

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| `GET` | `.../sprints/{sprint_id}/tickets` | `?status=` | `list[TaskRead]` | Tasks linked to this sprint |
| `POST` | `.../sprints/{sprint_id}/tickets` | `{ task_ids: UUID[] }` | `list[SprintTicketRead]` | Add existing backlog tasks to sprint |
| `DELETE` | `.../sprints/{sprint_id}/tickets/{task_id}` | — | `204` | Remove task from sprint (back to unassigned backlog) |
| `PATCH` | `.../sprints/{sprint_id}/tickets/reorder` | `{ task_ids: UUID[] }` | `204` | Update ticket positions within sprint |

### 3.4 Backlog (board-level, non-sprint-specific)

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| `GET` | `/boards/{board_id}/backlog` | `?sprint_id=&unassigned=true` | `list[TaskRead]` | All `is_backlog=True` tasks; filterable |
| `POST` | `/boards/{board_id}/backlog` | `TaskCreate` | `TaskRead` | Creates task with `is_backlog=True` |

### 3.5 Sprint Webhooks

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| `GET` | `/boards/{board_id}/sprint-webhooks` | — | `list[SprintWebhookRead]` | |
| `POST` | `/boards/{board_id}/sprint-webhooks` | `SprintWebhookCreate` | `SprintWebhookRead` | |
| `PATCH` | `/boards/{board_id}/sprint-webhooks/{webhook_id}` | `SprintWebhookUpdate` | `SprintWebhookRead` | |
| `DELETE` | `/boards/{board_id}/sprint-webhooks/{webhook_id}` | — | `204` | |

### 3.6 Board Settings Extension

The existing `PATCH /boards/{board_id}` endpoint accepts a new optional field:

```json
{ "auto_advance_sprint": true }
```

### 3.7 Webhook Payload Shape

When a sprint lifecycle event fires:

```json
POST <configured_url>
Headers:
  Content-Type: application/json
  X-Openclaw-Event: sprint_completed
  X-Openclaw-Signature: sha256=<hmac>
  X-Openclaw-Board-Id: <board_id>

Body:
{
  "event": "sprint_completed",
  "sprint": {
    "id": "...",
    "name": "Sprint 3",
    "goal": "Ship backlog feature",
    "status": "completed",
    "started_at": "2026-03-20T10:00:00Z",
    "completed_at": "2026-03-31T14:30:00Z",
    "board_id": "...",
    "ticket_count": 12,
    "tickets_completed": 12,
    "tickets_cancelled": 0
  },
  "board": {
    "id": "...",
    "name": "Core Platform",
    "slug": "core-platform"
  },
  "timestamp": "2026-03-31T14:30:00Z"
}
```

---

## 4. Backend Service Logic

### 4.1 `SprintService` (new file: `backend/app/services/sprint_lifecycle.py`)

Encapsulates all sprint state transitions and side-effects.

#### `start_sprint(board_id, sprint_id)`
1. Verify no active sprint exists on this board (raise `409 Conflict` if one does).
2. Set sprint `status = 'active'`, `started_at = now()`.
3. For every `sprint_ticket` in this sprint:
   - Set `task.is_backlog = False`, `task.status = 'inbox'`.
4. Create an `ActivityEvent` (`event_type = 'sprint_started'`).
5. Dispatch `sprint_started` webhook if configured.

#### `check_sprint_completion(board_id)` — called on every task status change
1. Find the active sprint for this board.
2. If no active sprint, return.
3. Count sprint tickets where `task.status != 'done'`.
4. If count == 0 → call `complete_sprint()`.

#### `complete_sprint(board_id, sprint_id)`
1. Set sprint `status = 'completed'`, `completed_at = now()`.
2. For every sprint ticket where `task.status == 'done'`:
   - Set `task.is_backlog = True` (archives it off the board).
   - The board snapshot query already filters `is_backlog = False`, so they vanish from the board.
3. Create `ActivityEvent` (`event_type = 'sprint_completed'`).
4. Dispatch `sprint_completed` webhook.
5. If `board.auto_advance_sprint` is `True`:
   - Find next sprint with `status = 'queued'` ordered by `position`.
   - If found → call `start_sprint()`.

#### `cancel_sprint(board_id, sprint_id)`
1. Set sprint `status = 'cancelled'`.
2. For sprint tickets where `task.status != 'done'`:
   - Set `task.is_backlog = True`, `task.status = 'inbox'` (return to backlog).
3. For sprint tickets where `task.status == 'done'`:
   - Keep `is_backlog = True` (archive).
4. Create `ActivityEvent`.
5. Dispatch `sprint_cancelled` webhook.

### 4.2 Integration point — task status update hook

In the existing `PATCH /boards/{board_id}/tasks/{task_id}` handler (after status is updated):

```python
# After successful status update to "done"
if new_status == "done":
    await sprint_service.check_sprint_completion(board_id)
```

This is the **only** change to existing task code — a single async call at the end of the
existing handler, wrapped in a try/except so it cannot break the existing flow.

### 4.3 Board snapshot query update

The existing `GET /boards/{board_id}/snapshot` query must add a filter:

```python
.where(Task.is_backlog == False)  # noqa: E712
```

This ensures backlog tasks never appear on the Kanban board. Since `is_backlog` defaults to
`False`, all existing tasks are unaffected.

### 4.4 What "archived off the board" means

When a sprint completes, done tickets get `is_backlog = True`. This removes them from the
board snapshot without deleting them. They remain queryable via the backlog API
(`GET /boards/{board_id}/backlog?sprint_id=<completed_sprint_id>`) for historical reference.

---

## 5. Schemas

### 5.1 `backend/app/schemas/sprints.py`

```python
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Literal

SprintStatus = Literal["draft", "queued", "active", "completed", "cancelled"]

class SprintCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    goal: str | None = None

class SprintUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    goal: str | None = None
    status: Literal["queued"] | None = None  # only draft → queued allowed here
    position: int | None = None

class SprintRead(BaseModel):
    id: UUID
    board_id: UUID
    name: str
    slug: str
    goal: str | None
    position: int
    status: SprintStatus
    started_at: datetime | None
    completed_at: datetime | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    ticket_count: int = 0
    tickets_done_count: int = 0

class SprintTicketRead(BaseModel):
    id: UUID
    sprint_id: UUID
    task_id: UUID
    position: int
    created_at: datetime

class SprintWebhookCreate(BaseModel):
    url: str = Field(..., min_length=1)
    events: list[str] = ["sprint_completed"]
    enabled: bool = True

class SprintWebhookUpdate(BaseModel):
    url: str | None = None
    events: list[str] | None = None
    enabled: bool | None = None

class SprintWebhookRead(BaseModel):
    id: UUID
    board_id: UUID
    url: str
    secret: str
    events: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime
```

---

## 6. Frontend

### 6.1 New sidebar link

In `DashboardSidebar.tsx`, add a **Backlog** link in the Boards section, between "Boards" and "Channels":

```
Boards:
  • Board groups    /board-groups
  • Boards          /boards
  ▸ Backlog         /backlog        ← NEW
  • Channels        /channels
  • Planning        /planning
  ...
```

Icon suggestion: `Layers` or `ListTodo` from lucide-react (consistent with existing icon set).

### 6.2 Color Scheme

The dashboard uses a consistent colour vocabulary. The backlog/sprint pages **must** follow it:

| Role | Tailwind classes | Where used today |
|------|-----------------|------------------|
| **Primary accent** | `bg-orange-500`, `text-orange-500`, `hover:bg-orange-600` | Planning buttons, chat bubbles, CTAs |
| **Selection / active highlight** | `bg-orange-50 text-orange-800` | Planning board selector, plan list selected row |
| **Focus rings** | `focus:border-orange-400 focus:ring-orange-400` | Planning inputs, modals |
| **Sidebar active link** | `bg-blue-100 text-blue-800 font-medium` | All sidebar links (keep blue for nav consistency) |
| **Status badges** | `bg-orange-100 text-orange-700` (active), `bg-slate-100 text-slate-600` (draft), `bg-green-100 text-green-700` (done), `bg-amber-100 text-amber-700` (cancelled) | Plan status badge — reuse same palette for sprint status |
| **Warnings / pending states** | `border-amber-200 bg-amber-50 text-amber-700` | Alert banners, pending-approval dots |
| **Neutral / background** | `bg-slate-50` (page), `bg-white` (cards), `border-slate-200` | Everywhere |
| **Destructive** | `bg-red-100 text-red-700 hover:bg-red-200` | Delete confirm buttons |

**Concrete rules for the backlog page**:

- Primary action buttons ("Start Sprint", "Queue Sprint", "+ New Ticket", "+ New Sprint"): `bg-orange-500 hover:bg-orange-600 text-white`.
- Selected sprint in the left panel: `bg-orange-50 text-orange-800` (mirrors plan list).
- Sprint status badges: reuse the `PlanStatusBadge` colour mapping — `draft` slate, `queued` orange-100, `active` orange-100, `completed` green-100, `cancelled` amber-100.
- Progress bar fill: `bg-orange-500` on a `bg-slate-200` track.
- Sprint banner on the board page: `border-orange-200 bg-orange-50 text-orange-800` with an orange progress bar.
- Input focus: `focus:border-orange-400 focus:ring-orange-400` (same as planning modals).
- Text links and empty-state CTAs: `text-orange-500 hover:text-orange-600`.

This keeps the entire Boards → Planning → Backlog area feeling like one cohesive orange-accented product section, distinct from the blue channel/admin areas.

### 6.3 Route: `/backlog`

**Page**: Board selector → shows all boards with their sprint state.

### 6.4 Route: `/backlog/[boardId]`

**Primary backlog view** — two-panel layout:

```
┌─────────────────────────────────────────────────────────────┐
│  Board: Core Platform                    [+ New Ticket]     │
├─────────────────────┬───────────────────────────────────────┤
│  Sprints            │  Sprint Detail / Unassigned Backlog   │
│                     │                                       │
│  ► Sprint 4 (draft) │  Sprint 4 — "Ship notifications"     │
│    Sprint 3 (active)│  ┌──────────────────────────────┐     │
│    Sprint 2 (done)  │  │ ☐ Add email templates   med  │     │
│    Sprint 1 (done)  │  │ ☐ Wire up SendGrid      high │     │
│                     │  │ ☐ Add preferences UI     low  │     │
│  ─── Unassigned ─── │  └──────────────────────────────┘     │
│    3 tickets        │  [Start Sprint] [Queue Sprint]        │
│                     │                                       │
├─────────────────────┴───────────────────────────────────────┤
│  Board settings: ☐ Flow mode (auto-advance)                 │
│  Sprint webhooks: [Manage]                                  │
└─────────────────────────────────────────────────────────────┘
```

**Interactions**:
- Create new ticket → opens same `TaskCreate` form but sets `is_backlog = True`
- Drag tickets between "Unassigned" and sprint buckets
- Drag to reorder within a sprint
- "Start Sprint" button → `POST .../sprints/{id}/start`
- "Queue Sprint" → marks sprint as `queued` (next in line for flow mode)
- Active sprint shows progress bar (N of M tickets done)
- Completed sprints are collapsible with historical ticket list

### 6.5 Active Sprint Banner on Board Page

On the board page (`/boards/[boardId]`), if an active sprint exists, show a thin banner:

```
┌─────────────────────────────────────────────────────────────┐
│ 🏃 Sprint 3: "Ship notifications"  │  8/12 done  │ 67%    │
└─────────────────────────────────────────────────────────────┘
```

This is **read-only** on the board page — all sprint management happens in the backlog view.

### 6.6 API Client Regeneration

After adding the new backend routes, run `make api-gen` to regenerate the frontend API client
in `frontend/src/api/generated/`.

---

---

## 7. Planning → Tickets Integration

### 7.1 Overview

The Planning feature already lets users collaborate with the board lead agent on a markdown
plan and then **promote** that plan into a single board task. This section extends it so users
can also ask the lead agent to **decompose** a plan into multiple discrete backlog tickets
ready for sprint assignment.

This is primarily a **frontend + thin API** change. The heavy lifting is done by the existing
gateway agent conversation infrastructure — we just add a new prompt and a new endpoint for
the agent to push structured ticket data back.

### 7.2 User Flow

```
PlanDetail page (existing)
  ┌───────────────────────────────────────────────┐
  │  Plan: "Ship notifications"     [Promote ▾]   │
  │                                               │
  │  content preview / editor    │  agent chat     │
  │                              │                 │
  └───────────────────────────────────────────────┘
```

The existing "Promote to task" button becomes a **dropdown split-button**:

```
  ┌──────────────────────────┐
  │  Promote to task         │   ← existing (unchanged)
  ├──────────────────────────┤
  │  Break down into tickets │   ← NEW
  └──────────────────────────┘
```

Clicking **"Break down into tickets"**:

1. Frontend sends the plan content to the lead agent with a system prompt that instructs it
   to decompose the plan into tickets.
2. A "Generating tickets…" spinner appears in the plan detail area (or the chat panel).
3. The agent responds with structured JSON (a list of ticket objects).
4. The frontend renders a **ticket preview list** — editable titles, priority dropdowns,
   optional descriptions — so the user can review / tweak before committing.
5. The user clicks **"Add to backlog"** (optionally selecting a target sprint).
6. Frontend calls `POST /boards/{board_id}/backlog` once per ticket (or a batch endpoint)
   to create them as backlog tasks.

### 7.3 Backend Changes (minimal)

#### New endpoint: `POST /boards/{board_id}/plans/{plan_id}/decompose`

**Request**: empty body (the plan content is already stored server-side).

**Behaviour**:
1. Build a gateway prompt that includes the plan content and instructs the agent to return
   a JSON array of tickets:
   ```
   Break the following plan into discrete, actionable tickets.
   Return ONLY a JSON array inside a ```tickets``` fenced block.
   Each ticket object must have: title (string), description (string),
   priority ("low" | "medium" | "high" | "critical").
   ```
2. Dispatch to the gateway (same as `chat_plan`) and return immediately.
3. The agent pushes back via an extended `agent-update` endpoint (see below).

#### Extended `POST /boards/{board_id}/plans/{plan_id}/agent-update`

The existing `PlanAgentUpdateRequest` schema gains an optional field:

```python
class PlanAgentUpdateRequest(BaseModel):
    reply: str = ""
    content: str | None = None
    tickets: list[DecomposedTicket] | None = None  # NEW

class DecomposedTicket(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"  # low | medium | high | critical
```

When `tickets` is present, the plan model stores them in a new JSON column (`decomposed_tickets`)
so the frontend can fetch them on the next poll.

#### New column on `plans`

```sql
ALTER TABLE plans ADD COLUMN decomposed_tickets JSONB;
-- Nullable. Stores the agent-generated ticket list until the user commits them.
```

#### New schema addition to `PlanRead`

```python
class PlanRead(BaseModel):
    ...existing fields...
    decomposed_tickets: list[DecomposedTicket] | None = None
```

#### Batch backlog create (optional convenience endpoint)

```
POST /boards/{board_id}/backlog/batch
Body: { tickets: [ { title, description, priority, sprint_id? } ] }
Response: list[TaskRead]
```

This avoids N individual POST calls from the frontend. Each ticket is created with
`is_backlog = True`. If `sprint_id` is provided, a `sprint_ticket` link is also created.

### 7.4 Frontend Changes

All changes are inside the existing `frontend/src/components/planning/` directory:

#### `PlanDetail.tsx`

- Replace the "Promote to task" button with a split-button dropdown:
  - "Promote to task" (existing handler)
  - "Break down into tickets" (new handler)
- New handler `handleDecompose()`:
  1. `POST /plans/{id}/decompose`
  2. Start polling `GET /plans/{id}` watching for `decomposed_tickets` to be non-null
  3. When tickets arrive, set local state and render `<TicketPreviewList>`

#### New component: `TicketPreviewList.tsx`

- Renders below the plan content (or in a modal/drawer) when `decomposed_tickets` is present.
- Each ticket row: editable title input, priority dropdown, optional description toggle.
- Footer: sprint selector dropdown (lists draft/queued sprints + "Unassigned") +
  **"Add to backlog"** button (`bg-orange-500`).
- On submit: calls `POST /boards/{board_id}/backlog/batch`.
- On success: clears `decomposed_tickets` from plan, shows toast, optionally navigates
  to `/backlog/{boardId}`.

**Colour notes** (consistent with planning theme):
- Ticket preview cards: `bg-white border border-slate-200 rounded-lg`.
- Editable fields: `focus:border-orange-400 focus:ring-orange-400`.
- Add-to-backlog button: `bg-orange-500 hover:bg-orange-600 text-white`.
- Sprint selector: standard slate input with orange focus ring.
- "Generating tickets…" state: `text-orange-500` spinner with `text-slate-500` label.

### 7.5 Planning Service Addition

Add to `backend/app/services/planning.py`:

```python
def build_decompose_prompt(plan_content: str) -> str:
    """Build prompt instructing the agent to break a plan into tickets."""
    return (
        "Break the following plan into discrete, actionable work tickets.\n"
        "Return ONLY a JSON array inside a ```tickets``` fenced code block.\n"
        "Each object: {title: string, description: string, "
        'priority: "low"|"medium"|"high"|"critical"}.\n\n'
        f"Plan content:\n{plan_content}"
    )


def extract_decomposed_tickets(agent_reply: str) -> list[dict] | None:
    """Extract tickets JSON from agent reply."""
    match = re.search(r"```tickets\s*\n(.+?)\n```", agent_reply, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
```

### 7.6 Sequence Diagram

```
User                     Frontend              Backend API            Gateway Agent
  │                         │                      │                       │
  │ click "Break down"      │                      │                       │
  │────────────────────────►│                      │                       │
  │                         │  POST /decompose     │                       │
  │                         │─────────────────────►│                       │
  │                         │                      │  dispatch prompt      │
  │                         │                      │──────────────────────►│
  │                         │      202 Accepted    │                       │
  │                         │◄─────────────────────│                       │
  │  spinner                │                      │                       │
  │◄────────────────────────│                      │                       │
  │                         │                      │   POST /agent-update  │
  │                         │                      │   { tickets: [...] }  │
  │                         │                      │◄──────────────────────│
  │                         │                      │   stored on plan      │
  │                         │  poll GET /plans/{id}│                       │
  │                         │─────────────────────►│                       │
  │                         │  { decomposed_tickets│: [...] }              │
  │                         │◄─────────────────────│                       │
  │  ticket preview list    │                      │                       │
  │◄────────────────────────│                      │                       │
  │                         │                      │                       │
  │ edit + "Add to backlog" │                      │                       │
  │────────────────────────►│                      │                       │
  │                         │ POST /backlog/batch   │                       │
  │                         │─────────────────────►│                       │
  │                         │   list[TaskRead]     │                       │
  │                         │◄─────────────────────│                       │
  │  success toast          │                      │                       │
  │◄────────────────────────│                      │                       │
```

---

## 8. Security

| Concern | Approach |
|---------|----------|
| **Org scoping** | All new tables extend `TenantScoped`; queries always filter by `organization_id` (same pattern as boards, tasks). |
| **Board access** | Sprint routes inherit the same `get_board_with_access()` dependency used by task routes. |
| **Agent auth** | Agent token auth can read sprint state but cannot start/complete/cancel sprints (user-only actions). |
| **Webhook secrets** | Sprint webhook secrets are auto-generated (32-byte hex), stored hashed. Payloads are HMAC-SHA256 signed. Same pattern as `board_webhooks`. |
| **Rate limiting** | Sprint start/complete are idempotent-safe (partial unique index prevents double-active). |
| **Input validation** | Pydantic schemas validate all inputs. Sprint status transitions are enforced server-side (e.g. only `draft`/`queued` → `active`). |

---

## 9. Work Packages

### WP-1: Database & Models (backend)
**Effort**: Small  
**Files**: New migration, new model files, board model update

1. Create Alembic migration adding `sprints`, `sprint_tickets`, `sprint_webhooks` tables.
2. Add `auto_advance_sprint` column to `boards`.
3. Add `is_backlog` and `sprint_id` columns to `tasks`.
4. Add `decomposed_tickets` JSON column to `plans`.
5. Create `backend/app/models/sprints.py` (Sprint, SprintTicket).
6. Create `backend/app/models/sprint_webhooks.py`.
7. Update `backend/app/models/__init__.py` exports.
8. Update `Board` model with `auto_advance_sprint` field.
9. Update `Task` model with `is_backlog` and `sprint_id` fields.
10. Update `Plan` model with `decomposed_tickets` field.

### WP-2: Schemas (backend)
**Effort**: Small  
**Files**: New schema file, board/task schema updates, plan schema update

1. Create `backend/app/schemas/sprints.py` (see §5.1).
2. Add `auto_advance_sprint` to `BoardUpdate` / `BoardRead` schemas.
3. Add `is_backlog` and `sprint_id` to `TaskRead` schema.
4. Add `is_backlog` to `TaskCreate` schema (optional, default `False`).
5. Add `DecomposedTicket` schema + `decomposed_tickets` to `PlanRead`.
6. Add `tickets` field to `PlanAgentUpdateRequest`.

### WP-3: Sprint CRUD & Backlog API (backend)
**Effort**: Medium  
**Files**: New route file, router registration

1. Create `backend/app/api/sprints.py` with all routes from §3.1–3.4.
2. Register router in `backend/app/api/__init__.py`.
3. Unit tests: CRUD operations, access control, input validation.

### WP-4: Sprint Lifecycle Service (backend)
**Effort**: Medium  
**Files**: New service file, task API hook

1. Create `backend/app/services/sprint_lifecycle.py` (see §4.1).
2. Add `check_sprint_completion()` call in task update handler (§4.2).
3. Update board snapshot query to filter `is_backlog` (§4.3).
4. Unit tests: start, complete (auto & manual), cancel, flow mode, edge cases.

### WP-5: Sprint Webhook Dispatch (backend)
**Effort**: Small  
**Files**: New route file, service integration

1. Create `backend/app/api/sprint_webhooks.py` with CRUD routes (§3.5).
2. Implement webhook dispatch in sprint lifecycle service using existing
   `backend/app/services/webhooks/dispatch.py` infrastructure.
3. Unit tests: webhook CRUD, dispatch on sprint events, HMAC signing.

### WP-5b: Plan Decompose Endpoint & Service (backend)
**Effort**: Small  
**Files**: Plan API update, planning service update

1. Add `POST /plans/{plan_id}/decompose` endpoint to `backend/app/api/plans.py`.
2. Add `POST /boards/{board_id}/backlog/batch` endpoint to sprint API.
3. Extend `agent-update` handler to accept `tickets` field.
4. Add `build_decompose_prompt()` and `extract_decomposed_tickets()` to planning service (§7.5).
5. Unit tests: decompose dispatch, agent-update with tickets, batch backlog create.

### WP-6: Backlog Frontend Page
**Effort**: Large  
**Files**: New page components, sidebar update, API client regen

1. Add "Backlog" link to `DashboardSidebar.tsx`.
2. Create `/backlog` route (board selector).
3. Create `/backlog/[boardId]` route (main backlog/sprint view — §6.4).
4. Follow the colour rules in §6.2 — all orange accents, slate neutrals.
5. Components:
   - `SprintList` — left panel, sprint cards with status badges
   - `SprintDetail` — right panel, ticket list with drag-and-drop
   - `SprintStatusBadge` — reuses same colour mapping as `PlanStatusBadge`
   - `BacklogTicketForm` — ticket creation form (reuse existing task form)
   - `SprintSettingsPanel` — flow mode toggle, webhook config
   - `SprintProgressBar` — orange fill on slate track
6. Run `make api-gen` to generate API client hooks.
7. Frontend tests with vitest + Testing Library.

### WP-6b: Plan → Tickets Frontend
**Effort**: Medium  
**Files**: Planning component updates, new TicketPreviewList component

1. Update `PlanDetail.tsx` — replace "Promote to task" button with split-button dropdown
   ("Promote to task" + "Break down into tickets"). Use orange accent colours.
2. Create `TicketPreviewList.tsx` component (§7.4) — editable ticket list rendered from
   `decomposed_tickets`, sprint selector, "Add to backlog" CTA.
3. Wire up `handleDecompose()` → POST decompose → poll → render preview → batch create.
4. Add `decomposePlan()` and `batchCreateBacklog()` to `frontend/src/api/plans.ts`.
5. Frontend tests with vitest + Testing Library.

### WP-7: Board Page Sprint Banner
**Effort**: Small  
**Files**: Board page update

1. Fetch active sprint in board page (single API call).
2. Render `SprintProgressBanner` component (§6.4).
3. No changes to board functionality — purely additive read-only UI.

### WP-8: Integration Tests & Documentation
**Effort**: Small  
**Files**: Test files, docs update

1. End-to-end test: create backlog tickets → assign to sprint → start sprint →
   complete all tickets → verify auto-completion → verify webhook fires →
   verify flow mode starts next sprint.
2. Update `docs/` with backlog/sprint documentation.
3. Update `CONTRIBUTING.md` if needed.

---

## 10. Migration Safety

| Risk | Mitigation |
|------|------------|
| Existing tasks appear in backlog | `is_backlog` defaults to `False` — all existing tasks remain on the board. |
| Board snapshot breaks | Filter `is_backlog == False` returns the same results as today (all existing tasks have `is_backlog = False`). |
| Sprint table empty | All sprint logic is gated on "if active sprint exists" — no sprint = no behavior change. |
| Task status update slower | Single async check added; returns immediately if no active sprint. |
| Rollback | Migration is reversible: drop new tables/columns, remove new API routes. No existing data is modified. |

---

## 11. Suggested Implementation Order

```
WP-1 → WP-2 → WP-3 → WP-4 → WP-5 → WP-5b → WP-6 → WP-6b → WP-7 → WP-8
 DB    Schema   API   Service Webhook Decompose Backlog Tickets Banner Tests
```

WP-1 through WP-5b can be done as a single backend PR (or split 5b out if preferred).  
WP-6, WP-6b and WP-7 can be a separate frontend PR (depends on `make api-gen` after backend merges).  
WP-8 spans both.

---

## 12. Future Considerations (out of scope)

- **Sprint velocity / burndown charts** — can be computed from `started_at`, `completed_at`,
  and task timestamps. Good candidate for a follow-up dashboard widget.
- **Sprint capacity planning** — story points or time estimates on tasks.
- **Cross-board sprints** — a sprint spanning multiple boards in a board group.
- **Recurring sprints** — auto-create the next sprint with a cadence (e.g. every 2 weeks).
- **Backlog prioritization with AI** — let the lead agent suggest sprint contents.
