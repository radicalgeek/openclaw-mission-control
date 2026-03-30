# Planning Feature — Comprehensive Implementation Plan

> **Feature**: A wiki-like planning workspace where operators chat with a board's lead agent to collaboratively build, iterate on, and finalize markdown planning documents. Completed plans can be promoted to board tasks and tracked through to completion.

---

## 1. Feature Overview

### 1.1 User Story

As an operator, I want to:

1. Navigate to a **Planning** section from the sidebar.
2. Select a board and see all my planning documents for that board.
3. Open a planning document and **chat with the board's lead agent** in a conversational interface.
4. Collaboratively build and iterate on a **markdown plan** through the chat.
5. **Directly edit the plan markdown** at any time — switch between a rendered preview and a live editor.
6. When satisfied, click **"Add as task"** to promote the plan to a board task.
7. When the resulting task is marked done, the plan is automatically marked **complete**.

### 1.2 Core Concepts

| Concept | Description |
|---------|-------------|
| **Plan** | A markdown document scoped to a board, created and refined through conversation with the lead agent **or direct manual editing**. Has a lifecycle: `draft` → `active` → `completed` / `archived`. |
| **Planning Session** | The conversational thread between the operator and the board lead agent, persisted as a message transcript (same pattern as board onboarding). |
| **Plan → Task Link** | A one-to-one relationship from a plan to a board task. When the task reaches `done`, the plan status flips to `completed`. |

---

## 2. Information Architecture

```
/planning                         → Board selector (list boards with plan counts)
/planning/[boardId]               → Plan list for a board + create new plan
/planning/[boardId]/[planId]      → Split-pane: chat (left) + markdown editor/preview (right)
```

---

## 3. Data Model

### 3.1 New Table: `plans`

> File: `backend/app/models/plans.py`

Follows the existing `TenantScoped` base class pattern (same as `Task`, `Board`, `Channel`).

```python
class Plan(TenantScoped, table=True):
    __tablename__ = "plans"

    id: UUID                          # PK, uuid4
    board_id: UUID                    # FK → boards.id (indexed)
    title: str                        # Plan title (editable)
    slug: str                         # URL-friendly identifier (indexed)
    content: str                      # The markdown document body (default "")
    status: str                       # "draft" | "active" | "completed" | "archived" (indexed)
    created_by_user_id: UUID | None   # FK → users.id
    task_id: UUID | None              # FK → tasks.id (nullable, set when promoted)
    session_key: str                  # Gateway session identifier for agent conversation
    messages: list[dict] | None       # JSON — chat transcript (same shape as BoardOnboardingSession)
    created_at: datetime
    updated_at: datetime
```

**Key design decisions:**
- `content` stores the current markdown. Updated by agent replies (extracted from chat) **and** by direct user edits via the markdown editor. Both sources write to this same field.
- `messages` stores the full chat transcript as JSON (matching the onboarding pattern in `BoardOnboardingSession`).
- `session_key` ties the plan to a persistent gateway session so the agent retains context across interactions.
- `task_id` is set when the user promotes the plan to a task. This is a nullable 1:1 link.
- `slug` is auto-generated from the title for URL use.

### 3.2 Database Migration

> File: `backend/migrations/versions/XXXX_add_plans_table.py`

Standard Alembic migration adding the `plans` table with:
- Indexes on `board_id`, `status`, `slug`, `task_id`
- Foreign keys to `boards`, `users`, `tasks`

---

## 4. Backend API

### 4.1 New Router: `backend/app/api/plans.py`

Prefix: `/boards/{board_id}/plans`  
Tags: `["plans"]`

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/boards/{board_id}/plans` | List plans for a board (filterable by status) | `require_org_member` |
| `POST` | `/boards/{board_id}/plans` | Create a new plan (initializes gateway session) | `require_user_auth` |
| `GET` | `/boards/{board_id}/plans/{plan_id}` | Get plan detail (content + messages + status) | `require_org_member` |
| `PATCH` | `/boards/{board_id}/plans/{plan_id}` | Update plan title, content, or status | `require_user_auth` |
| `DELETE` | `/boards/{board_id}/plans/{plan_id}` | Soft-delete (archive) a plan | `require_user_auth` |
| `POST` | `/boards/{board_id}/plans/{plan_id}/chat` | Send a message to the lead agent, receive updated plan | `require_user_auth` |
| `POST` | `/boards/{board_id}/plans/{plan_id}/promote` | Promote plan to a board task | `require_user_auth` |

### 4.2 New Schemas: `backend/app/schemas/plans.py`

```python
class PlanCreate(SQLModel):
    title: NonEmptyStr
    initial_prompt: str | None = None    # Optional kickoff message to agent

class PlanUpdate(SQLModel):
    title: str | None = None
    content: str | None = None              # Direct manual content edits from the editor
    status: str | None = None              # "draft" | "active" | "archived"

class PlanRead(SQLModel):
    id: UUID
    board_id: UUID
    title: str
    slug: str
    content: str
    status: str
    created_by_user_id: UUID | None
    task_id: UUID | None
    task_status: str | None              # Denormalized from linked task for display
    messages: list[dict] | None
    created_at: datetime
    updated_at: datetime

class PlanChatRequest(SQLModel):
    message: NonEmptyStr                 # User's message to the agent

class PlanChatResponse(SQLModel):
    messages: list[dict]                 # Updated full transcript
    content: str                         # Updated plan markdown
    agent_reply: str                     # The agent's latest reply (for display)

class PlanPromoteRequest(SQLModel):
    task_title: str | None = None        # Override title (defaults to plan title)
    task_priority: str = "medium"
    assigned_agent_id: UUID | None = None
```

### 4.3 New Service: `backend/app/services/planning.py`

Responsibilities:
- **Session management**: Create/reuse gateway sessions for plan conversations (mirrors `BoardOnboardingMessagingService`).
- **Prompt engineering**: Build the system prompt instructing the lead agent to collaboratively produce a markdown plan.
- **Content extraction**: Parse agent responses to extract updated markdown content from the conversation.
- **Task promotion**: Create a task from the plan and establish the bidirectional link.
- **Status sync**: React to task status changes to auto-complete plans (via a hook in the task update flow).

### 4.4 New Service: `backend/app/services/openclaw/planning_service.py`

Follows the exact pattern of `BoardOnboardingMessagingService`:

```python
class PlanningMessagingService(AbstractGatewayMessagingService):
    async def dispatch_plan_message(
        self,
        *,
        board: Board,
        plan: Plan,
        message: str,
        correlation_id: str | None = None,
    ) -> None:
        # Resolve gateway config for the board
        # Send message to the existing session (plan.session_key)
        # Handle errors with map_gateway_error_to_http_exception
        ...

    async def dispatch_plan_start(
        self,
        *,
        board: Board,
        prompt: str,
        correlation_id: str | None = None,
    ) -> str:
        # Initialize a new gateway session
        # Send the system prompt + initial user message
        # Return the session_key
        ...
```

### 4.5 Task Status Hook

> File: `backend/app/api/tasks.py` (modify existing)

In the task update handler, after a task transitions to `done`:

```python
# Check if this task is linked to a plan
plan = await session.exec(select(Plan).where(Plan.task_id == task.id))
if plan:
    plan.status = "completed"
    plan.updated_at = utcnow()
    session.add(plan)
```

This is a lightweight check (indexed FK lookup) and follows the same pattern used for `ApprovalTaskLink` updates.

### 4.6 Gateway Prompt Template

> File: `backend/templates/PLAN_CHAT.md.j2`

```jinja2
You are the lead agent for board "{{ board_name }}".
The user is collaborating with you to build a planning document.

Board objective: {{ board_objective or "Not yet defined" }}

## Instructions
- Help the user create a structured markdown planning document.
- After each exchange, output an updated version of the full plan document 
  wrapped in a ```plan``` fenced code block.
- Be collaborative: ask clarifying questions, suggest structure, 
  identify gaps, and propose improvements.
- Keep the conversation focused on the plan content.

## Current Plan
{{ current_content or "(Empty — let's start building!)" }}
```

### 4.7 Wire Up Router

> File: `backend/app/api/__init__.py` (modify)

Register the new router:
```python
from app.api.plans import router as plans_router
app.include_router(plans_router, prefix="/api/v1")
```

---

## 5. Frontend

### 5.1 New Routes

```
frontend/src/app/planning/page.tsx                    → Board selector
frontend/src/app/planning/[boardId]/page.tsx           → Plan list
frontend/src/app/planning/[boardId]/[planId]/page.tsx  → Plan editor (chat + preview)
```

### 5.2 New Components

```
frontend/src/components/planning/
├── PlanningLayout.tsx            — Page wrapper with board context
├── BoardPlanSelector.tsx         — Board list with plan counts per board
├── PlanList.tsx                  — List of plans for the selected board
│   ├── PlanRow.tsx               — Single plan row (title, status badge, timestamps)
│   ├── PlanStatusBadge.tsx       — Colored badge for draft/active/completed/archived
│   └── NewPlanButton.tsx         — "New plan" creation trigger
├── PlanEditor.tsx                — Split-pane: chat + markdown preview
│   ├── PlanChat.tsx              — Chat panel (left side)
│   │   ├── PlanMessageList.tsx   — Scrollable chat transcript
│   │   ├── PlanMessageBubble.tsx — Individual message (user vs agent styling)
│   │   └── PlanChatComposer.tsx  — Text input + send (reuse BoardChatComposer pattern)
│   ├── PlanContentPanel.tsx      — Right panel: toggle between preview and edit modes
│   │   ├── PlanPreview.tsx       — Rendered markdown view (uses <Markdown /> atom)
│   │   └── PlanMarkdownEditor.tsx — Raw markdown textarea with live editing
│   ├── PlanToolbar.tsx           — Actions: Edit/Preview toggle, Edit title, Promote to task, Archive
│   └── PromoteToTaskModal.tsx    — Confirmation dialog for task promotion
└── PlanCompleteBanner.tsx        — Banner shown when linked task is done
```

### 5.3 Sidebar Navigation

> File: `frontend/src/components/organisms/DashboardSidebar.tsx` (modify)

Add a new nav link in the "Boards" section, after "Channels" and before "Tags":

```tsx
<Link href="/planning" className={cn(...)}>
  <FileText className="h-4 w-4" />
  Planning
</Link>
```

Icon: `FileText` from `lucide-react` (wiki/document metaphor).

### 5.4 Component Details

#### 5.4.1 BoardPlanSelector (`/planning`)

- Reuses the same `useListBoardsApiV1BoardsGet` hook used by the dashboard.
- Displays each board as a card/row with:
  - Board name, description
  - Plan count badge (fetched from a new lightweight endpoint or included in board list response)
- Clicking a board navigates to `/planning/[boardId]`.

#### 5.4.2 PlanList (`/planning/[boardId]`)

- Header: board name + "New plan" button.
- Filterable tabs: **All** | **Draft** | **Active** | **Completed** | **Archived**.
- Each row shows: title, status badge, last updated, linked task status (if promoted).
- Clicking a plan navigates to the plan editor.
- "New plan" opens a modal or inline form for title entry, then navigates to the editor.

#### 5.4.3 PlanEditor (`/planning/[boardId]/[planId]`)

**Layout**: Horizontal split pane (resizable).

**Left panel — Chat**:
- Scrollable message list showing the full conversation transcript.
- Messages styled differently for user (right-aligned, blue) vs agent (left-aligned, grey).
- Agent messages that contain plan updates are highlighted with a subtle indicator.
- Chat composer at the bottom (reuses the `BoardChatComposer` pattern with `@mention` support).
- Sending a message calls `POST /boards/{boardId}/plans/{planId}/chat`.
- On response, both the transcript and the markdown preview update.

**Right panel — Content (preview / edit)**:
- **Two modes**, toggled via an **Edit / Preview** button in the toolbar:
  - **Preview mode** (default): Rendered markdown using the existing `<Markdown>` atom component. Read-only.
  - **Edit mode**: A full-height markdown textarea (`PlanMarkdownEditor`) where the user can directly modify the plan content. Includes:
    - Monospace font, line numbers, and basic syntax highlighting (via a lightweight library or plain `<textarea>`).
    - Auto-save on blur or after a short debounce (300 ms idle) — calls `PATCH /plans/{plan_id}` with the new `content`.
    - A subtle "unsaved changes" indicator while the debounce is pending.
    - When the user saves manual edits, the updated content is also injected into the next agent prompt so the agent stays in sync.
- Sticky toolbar at top with:
  - **Edit / Preview toggle** button (pencil icon ↔ eye icon)
  - **Edit title** (inline editable)
  - **"Add as task"** button (opens `PromoteToTaskModal`) — only shown for `draft`/`active` plans, hidden once promoted
  - **Status indicator** showing plan and linked task status
  - **Archive** button
- If the plan has been promoted and the task is `done`, show a `PlanCompleteBanner` at the top.
- If the user is in edit mode and an agent response arrives with a plan update, a non-blocking toast notification appears: _"The agent updated the plan. Switch to preview to see changes."_ The editor content is **not** overwritten mid-edit — the user's in-progress edits take priority. The agent's version is held in state and merged on the next save or mode switch.

#### 5.4.4 PromoteToTaskModal

- Confirmation dialog pre-filled with:
  - Task title (defaults to plan title, editable)
  - Priority selector (medium default)
  - Agent assignment dropdown (pre-select board lead)
- On confirm, calls `POST /boards/{boardId}/plans/{planId}/promote`.
- On success, the plan transitions to `active` status and displays a link to the new task.

### 5.5 API Client

After backend endpoints are implemented:
1. Run `make api-gen` to regenerate the frontend API client in `frontend/src/api/generated/`.
2. New generated hooks will include:
   - `useListPlansApiV1BoardsBoardIdPlansGet`
   - `useGetPlanApiV1BoardsBoardIdPlansPlanIdGet`
   - `createPlanApiV1BoardsBoardIdPlansPost`
   - `updatePlanApiV1BoardsBoardIdPlansPlanIdPatch`
   - `chatPlanApiV1BoardsBoardIdPlansPlanIdChatPost`
   - `promotePlanApiV1BoardsBoardIdPlansPlanIdPromotePost`

### 5.6 Real-Time Updates

The plan editor should poll for updates (same pattern as onboarding):
- Poll `GET /boards/{boardId}/plans/{planId}` every 2-3 seconds while the chat is "waiting" for an agent response.
- Use a `isWaiting` state flag set after sending a message, cleared when the agent reply arrives.
- Future enhancement: migrate to SSE/WebSocket (matching the task board's `EventSourceResponse` pattern).

---

## 6. Plan ↔ Task Lifecycle

### 6.1 State Machine

```
                    ┌─────────┐
         create     │  draft  │
        ────────►   │         │
                    └────┬────┘
                         │ promote to task
                         ▼
                    ┌─────────┐
                    │  active │──────────────┐
                    │         │              │ user archives
                    └────┬────┘              ▼
                         │            ┌──────────┐
                         │            │ archived  │
                         │            └──────────┘
                         │ linked task → done
                         ▼
                    ┌───────────┐
                    │ completed │
                    └───────────┘
```

### 6.2 Task Creation (Promote)

When calling `POST /plans/{plan_id}/promote`:

1. Validate plan is in `draft` or `active` status and has no existing `task_id`.
2. Create a new `Task` on the board with:
   - `title`: from request or plan title
   - `description`: plan markdown content (full plan as task description)
   - `status`: `inbox`
   - `priority`: from request
   - `assigned_agent_id`: from request (defaults to board lead)
   - `created_by_user_id`: current user
   - `auto_created`: `True`
   - `auto_reason`: `"promoted_from_plan"`
3. Set `plan.task_id = task.id` and `plan.status = "active"`.
4. Record an activity event: `"plan_promoted_to_task"`.

### 6.3 Task Completion Hook

When a task transitions to `done` (in the existing task update handler):

1. Query for any `Plan` where `task_id == task.id`.
2. If found, set `plan.status = "completed"` and `plan.updated_at = utcnow()`.
3. Record an activity event: `"plan_completed_via_task"`.

### 6.4 Edge Cases

- **Task deleted**: If a linked task is deleted, set `plan.task_id = None` and revert `plan.status` to `draft`.
- **Task reopened**: If a task transitions from `done` back to another status, set `plan.status` back to `active`.
- **Plan archived**: Archiving a plan does NOT affect the linked task. The task continues independently.
- **Multiple promotes**: A plan can only be promoted once. The "Add as task" button is hidden once `task_id` is set.

---

## 7. Agent Interaction Design

### 7.1 System Prompt Strategy

The planning agent interaction uses the board's existing lead agent through the gateway. The system prompt (in `PLAN_CHAT.md.j2`) instructs the agent to:

1. Act as a collaborative planning partner.
2. After each exchange, output the full updated plan in a fenced `plan` code block.
3. Ask clarifying questions to improve plan quality.
4. Suggest structure (sections, milestones, acceptance criteria).
5. Identify risks and dependencies.

### 7.2 Content Extraction

After each agent response, the backend parses the reply to extract the updated plan:

```python
def extract_plan_content(agent_reply: str) -> str | None:
    """Extract plan content from agent response.

    Looks for a fenced code block tagged 'plan':
        ```plan
        # My Plan
        ...
        ```
    """
    match = re.search(r'```plan\s*\n(.*?)```', agent_reply, re.DOTALL)
    return match.group(1).strip() if match else None
```

If no plan block is found, the `content` field is not updated (the agent is asking questions or having a discussion). The full reply is always appended to the transcript.

### 7.3 Chat Flow

1. **User sends message** → `POST /plans/{plan_id}/chat`
2. Backend appends `{role: "user", content: message}` to `plan.messages`.
3. Backend builds the full prompt context (system prompt + **current `plan.content`** + latest message). This ensures the agent always sees the latest content, including any manual edits the user made.
4. Backend dispatches to gateway via `PlanningMessagingService`.
5. Gateway agent processes and responds.
6. Backend receives response, appends `{role: "assistant", content: reply}` to `plan.messages`.
7. Backend extracts plan content (if present) and updates `plan.content`.
8. Returns `PlanChatResponse` (updated transcript + content + agent reply).

### 7.4 Manual Edit Flow

1. User switches to **Edit mode** in the right panel.
2. User modifies the markdown directly in the textarea.
3. On debounce/blur, the frontend calls `PATCH /plans/{plan_id}` with `{content: "..."}`.
4. Backend updates `plan.content` and `plan.updated_at`.
5. The next time the user sends a chat message, the agent prompt template includes the manually-edited content, so the agent is aware of all user changes.
6. If the user sends a chat message like _"I've updated section 3 — please review and improve it"_, the agent sees the current content and can respond accordingly.

### 7.5 Session Persistence

Each plan has its own `session_key` (gateway session). This ensures:
- The agent has full context of the conversation history.
- Multiple plans for the same board have independent conversations.
- The session persists across page reloads (same model as onboarding sessions).

---

## 8. Testing Strategy

### 8.1 Backend Unit Tests

> Files in `backend/tests/`

| Test File | Coverage |
|-----------|----------|
| `test_plans_api.py` | CRUD endpoints, auth checks, status filtering |
| `test_plans_promote.py` | Promote to task, duplicate promote guard, linked task status |
| `test_plans_chat.py` | Chat endpoint, transcript persistence, content extraction |
| `test_plans_task_hook.py` | Task done → plan completed, task delete → plan unlinked, task reopen |
| `test_plans_schema.py` | Schema validation, plan status transitions |

Key test cases:
- Auth: unauthenticated users cannot access plans.
- Auth: plans are board-scoped; cross-board access is denied.
- CRUD: create, list, get, update, delete lifecycle.
- Chat: message is appended to transcript, agent reply is parsed.
- Content extraction: `extract_plan_content` handles present/absent plan blocks.
- Manual edit: `PATCH` with content updates `plan.content` and `plan.updated_at`.
- Promote: creates a task with correct fields, sets plan.task_id.
- Promote guard: returns 409 if plan already promoted.
- Task hook: task done → plan completed; task deleted → plan unlinked.
- Status filtering: list plans by status works correctly.

### 8.2 Frontend Tests

> Files in `frontend/src/components/planning/` (co-located) and `frontend/src/app/planning/`

| Test File | Coverage |
|-----------|----------|
| `PlanList.test.tsx` | Renders plans, filters by status, handles empty state |
| `PlanEditor.test.tsx` | Split pane renders, chat/preview panels |
| `PlanChat.test.tsx` | Send message, display transcript, loading states |
| `PlanPreview.test.tsx` | Renders markdown, updates on content change |
| `PlanMarkdownEditor.test.tsx` | Edit mode renders textarea, debounce save fires PATCH, unsaved indicator |
| `PromoteToTaskModal.test.tsx` | Form validation, submit, success/error states |
| `PlanCompleteBanner.test.tsx` | Shows when task is done, hidden otherwise |
| `PlanStatusBadge.test.tsx` | Correct colors/labels for each status |

### 8.3 E2E Tests (Cypress)

> Files in `frontend/cypress/e2e/`

| Test File | Flows |
|-----------|-------|
| `planning_navigation.cy.ts` | Sidebar link → board selector → plan list → plan editor |
| `planning_crud.cy.ts` | Create plan, edit title, manually edit content, archive plan |
| `planning_promote.cy.ts` | Promote plan to task, verify task appears on board |

---

## 9. Migration & Feature Flag

### 9.1 Feature Flag

Add `PLANNING_ENABLED` to `backend/app/core/config.py` (follows the `CHANNELS_ENABLED` pattern):

```python
planning_enabled: bool = Field(default=False, alias="PLANNING_ENABLED")
```

All planning endpoints will check this flag and return `404` when disabled (same guard pattern as channels).

Frontend checks via a config endpoint or environment variable to conditionally render the sidebar item.

### 9.2 Migration Safety

- The `plans` table is additive (no existing table modifications in the initial migration).
- The task hook is a lightweight conditional check, zero impact on existing task flows when no plans exist.
- The sidebar link is conditionally rendered behind the feature flag.

---

## 10. Work Packages

### WP-1: Data Model & Migration
- Create `backend/app/models/plans.py`
- Create Alembic migration
- Register model in `backend/app/models/__init__.py`
- Add `PLANNING_ENABLED` config flag
- **Commit**: `feat(planning): WP-1 data model and migration`

### WP-2: Backend Schemas
- Create `backend/app/schemas/plans.py`
- Define `PlanCreate`, `PlanUpdate`, `PlanRead`, `PlanChatRequest`, `PlanChatResponse`, `PlanPromoteRequest`
- **Commit**: `feat(planning): WP-2 plan schemas`

### WP-3: Planning Service & Gateway Integration
- Create `backend/app/services/planning.py`
- Create `backend/app/services/openclaw/planning_service.py`
- Create `backend/templates/PLAN_CHAT.md.j2`
- Implement content extraction logic
- **Commit**: `feat(planning): WP-3 planning service and gateway integration`

### WP-4: API Endpoints
- Create `backend/app/api/plans.py`
- Implement all CRUD + chat + promote endpoints
- Register router in `backend/app/api/__init__.py` (or `main.py`)
- Add feature flag guard
- **Commit**: `feat(planning): WP-4 plan API endpoints`

### WP-5: Task ↔ Plan Lifecycle Hooks
- Modify `backend/app/api/tasks.py` to add plan completion hook on task done
- Handle task delete → unlink plan
- Handle task reopen → revert plan to active
- Add activity event recording
- **Commit**: `feat(planning): WP-5 task-plan lifecycle hooks`

### WP-6: Frontend — Planning Pages & Components
- Add "Planning" nav item to `DashboardSidebar.tsx`
- Create route pages: `/planning`, `/planning/[boardId]`, `/planning/[boardId]/[planId]`
- Create all components listed in §5.2
- Regenerate API client (`make api-gen`)
- **Commit**: `feat(planning): WP-6 frontend planning UI`

### WP-7: Frontend — Chat, Editor & Preview Integration
- Implement `PlanChat` with real-time polling
- Implement `PlanContentPanel` with edit/preview mode toggle
- Implement `PlanMarkdownEditor` with debounced auto-save, unsaved indicator, and conflict toast
- Implement `PlanPreview` with live markdown rendering
- Implement `PromoteToTaskModal` flow
- Implement `PlanCompleteBanner` for completed plans
- **Commit**: `feat(planning): WP-7 chat, editor and preview integration`

### WP-8: Tests & Documentation
- Backend unit tests (5 test files)
- Frontend component tests (7 test files)
- Cypress E2E tests (3 test files)
- Create `docs/planning.md`
- **Commit**: `feat(planning): WP-8 tests and documentation`

---

## 11. File Inventory

### New Backend Files
```
backend/app/models/plans.py
backend/app/schemas/plans.py
backend/app/api/plans.py
backend/app/services/planning.py
backend/app/services/openclaw/planning_service.py
backend/templates/PLAN_CHAT.md.j2
backend/migrations/versions/XXXX_add_plans_table.py
backend/tests/test_plans_api.py
backend/tests/test_plans_promote.py
backend/tests/test_plans_chat.py
backend/tests/test_plans_task_hook.py
backend/tests/test_plans_schema.py
```

### Modified Backend Files
```
backend/app/models/__init__.py            (register Plan model)
backend/app/api/__init__.py or main.py    (register plans router)
backend/app/core/config.py                (add PLANNING_ENABLED flag)
backend/app/api/tasks.py                  (add plan completion hook)
```

### New Frontend Files
```
frontend/src/app/planning/page.tsx
frontend/src/app/planning/[boardId]/page.tsx
frontend/src/app/planning/[boardId]/[planId]/page.tsx
frontend/src/components/planning/PlanningLayout.tsx
frontend/src/components/planning/BoardPlanSelector.tsx
frontend/src/components/planning/PlanList.tsx
frontend/src/components/planning/PlanRow.tsx
frontend/src/components/planning/PlanStatusBadge.tsx
frontend/src/components/planning/NewPlanButton.tsx
frontend/src/components/planning/PlanEditor.tsx
frontend/src/components/planning/PlanChat.tsx
frontend/src/components/planning/PlanMessageList.tsx
frontend/src/components/planning/PlanMessageBubble.tsx
frontend/src/components/planning/PlanChatComposer.tsx
frontend/src/components/planning/PlanContentPanel.tsx
frontend/src/components/planning/PlanPreview.tsx
frontend/src/components/planning/PlanMarkdownEditor.tsx
frontend/src/components/planning/PlanToolbar.tsx
frontend/src/components/planning/PromoteToTaskModal.tsx
frontend/src/components/planning/PlanCompleteBanner.tsx
frontend/cypress/e2e/planning_navigation.cy.ts
frontend/cypress/e2e/planning_crud.cy.ts
frontend/cypress/e2e/planning_promote.cy.ts
```

### Modified Frontend Files
```
frontend/src/components/organisms/DashboardSidebar.tsx   (add Planning nav item)
frontend/src/api/generated/                               (regenerate from updated OpenAPI spec)
```

### New Documentation Files
```
docs/planning.md
```

---

## 12. Dependencies & Risks

| Risk | Mitigation |
|------|------------|
| Gateway agent may not reliably emit `plan` fenced blocks | Fallback: if no plan block detected, show agent reply in chat but don't update preview. User can switch to edit mode and manually update the content themselves. |
| Long conversations may exceed gateway context window | Include conversation summary/rolling window in prompt. Only send last N messages + current plan content as context. |
| Plan content conflicts (user edits while agent updates) | When the user is in edit mode, agent plan updates are held in a pending state and surfaced via a toast notification. The user's in-progress edits are never overwritten. On mode switch or save, a simple "last write wins" merge applies. True concurrent OT/CRDT is a future enhancement. |
| Performance of task hook on high-volume boards | Hook is a single indexed query (`Plan.task_id == task.id`). Negligible overhead. |
| Feature flag coordination between backend and frontend | Backend returns `planning_enabled` in a config/health endpoint. Frontend conditionally renders sidebar and routes. |

---

## 13. Future Enhancements (Out of Scope for V1)

- **Real-time streaming**: SSE for agent responses (like the task board's `EventSourceResponse`).
- **Version history**: Track plan content revisions with diffs.
- **Conflict-free collaborative editing**: OT/CRDT for true simultaneous multi-user editing.
- **Plan templates**: Pre-built plan structures (sprint plan, project brief, design doc).
- **Multiple task links**: Allow a plan to generate multiple tasks (one per section/milestone).
- **Plan sharing**: Share plans across boards or with external stakeholders.
- **Export**: Export plans as PDF or standalone markdown files.
- **Collaborative editing**: Multiple users editing the same plan simultaneously.
