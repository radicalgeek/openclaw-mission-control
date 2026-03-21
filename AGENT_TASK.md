# Task: Implement Mission Control Channels Feature

## Your Mission
Implement the full Channels feature for OpenClaw Mission Control as described in `CHANNELS_PLAN.md`.
You are working on the `feat/channels` branch of the `radicalgeek/openclaw-mission-control` repo.

## Tech Stack
- **Backend**: Python 3.12, FastAPI (async), SQLModel + SQLAlchemy async, Alembic migrations, PostgreSQL
- **Frontend**: Next.js 14 (app router), TypeScript, Tailwind CSS
- **Patterns to follow**:
  - Models inherit from `TenantScoped` (see `backend/app/models/tenancy.py`)
  - Use `SQLModel` with `table=True` for DB models, separate Pydantic schemas in `backend/app/schemas/`
  - API routers follow the pattern in `backend/app/api/boards.py` and `backend/app/api/tasks.py`
  - Alembic migrations live in `backend/migrations/versions/`
  - Frontend pages use Next.js app router (`frontend/src/app/`)
  - Frontend components in `frontend/src/components/`
  - The existing webhook handler is in `backend/app/api/board_webhooks.py`
  - Task model is in `backend/app/models/tasks.py`
  - Board model is in `backend/app/models/boards.py`

## Critical Constraints
1. **Do NOT break existing functionality** — all existing tests must still pass
2. **Feature flag**: Wrap channel-related behaviour behind `settings.channels_enabled` (default `False`)
   Add `CHANNELS_ENABLED: bool = False` to `backend/app/core/config.py`
3. **Additive migrations only** — only ADD new tables and nullable columns (no destructive changes)
4. **The existing webhook → task pipeline is UNTOUCHED** — the channel hook is a downstream observer only, wrapped in try/except
5. **Legacy tasks** (without thread_id) must continue working exactly as before

## Work Order (sequential — do not skip ahead)

### WP-1: Database Schema & Migrations
- Create models: Channel, Thread, ThreadMessage, ChannelSubscription, UserChannelState
- Follow exact patterns from `backend/app/models/tasks.py` (SQLModel, TenantScoped, UUID PKs, utcnow())
- Add nullable `thread_id` FK to existing Task model
- Create Alembic migration (additive only)
- Create `backend/app/services/channel_lifecycle.py` with `on_board_created`, `on_board_deleted`, `on_board_lead_changed`, `on_agent_added_to_board`, `on_agent_removed_from_board`
- Commit: `feat(channels): WP-1 database schema and migrations`

### WP-2: Backend API Endpoints
- Create routers: `backend/app/api/channels.py`, `backend/app/api/threads.py`, `backend/app/api/messages.py`
- Create schemas in `backend/app/schemas/channels.py`, `threads.py`, `messages.py`
- Register routes in `backend/app/api/__init__.py` or `main.py` (follow existing pattern)
- Add subscription and state endpoints
- Modify `backend/app/api/tasks.py` to proxy comments to thread messages when `task.thread_id` is set
  (ONLY when task has a thread_id — legacy tasks untouched)
- Add lifecycle hook calls to `backend/app/api/boards.py` and `backend/app/api/agents.py`
  (wrap each in try/except — board/agent operations must never fail because of channel errors)
- Commit: `feat(channels): WP-2 backend API endpoints`

### WP-3: Agent Message Routing
- Extend `backend/app/services/openclaw/gateway_dispatch.py` to support channel_message envelope
- Add `backend/app/services/channel_agent_routing.py` with agent notification logic
- Commit: `feat(channels): WP-3 agent message routing`

### WP-4: Webhook → Channel Hook
- Create `backend/app/services/channel_thread_hook.py` with `on_task_created_by_webhook()`
- Create `backend/app/webhooks/classifier.py` and individual classifiers
- Add the hook call to the existing webhook ingest handler in `backend/app/api/board_webhooks.py`
  (AFTER task creation, wrapped in try/except — webhook processing must never fail)
- Add direct channel webhook endpoint
- Commit: `feat(channels): WP-4 webhook channel integration`

### WP-5: Task ↔ Thread Bidirectional Sync
- Update task comment API to proxy to thread messages when thread_id set
- Add thread context to task detail schema
- Commit: `feat(channels): WP-5 task-thread bidirectional sync`

### WP-6: Frontend — Channel Page & Components
- Add "Channels" nav item to `frontend/src/components/navigation/Sidebar.tsx`
- Create route `frontend/src/app/channels/page.tsx` and `[boardId]/page.tsx`
- Create all components listed in CHANNELS_PLAN.md under WP-6
- Hook into existing WebSocket for real-time updates
- Follow existing Tailwind + component patterns (look at `frontend/src/components/tasks/` for style reference)
- Commit: `feat(channels): WP-6 frontend channel UI`

### WP-7: Board Task View Integration
- Update `frontend/src/components/tasks/TaskDetail.tsx` to show thread context when linked
- Add thread indicators to task list
- Commit: `feat(channels): WP-7 board task view integration`

### WP-8: Tests & Documentation
- Backend tests in `backend/tests/` (follow existing test patterns)
- Frontend component tests
- Create `docs/channels.md`
- Commit: `feat(channels): WP-8 tests and documentation`

## After All WPs Done
1. Run `git push origin feat/channels` to push all commits
2. Run: `openclaw system event --text "Done: Channels feature implemented on feat/channels — 8 WPs complete, all commits pushed. Ready for review." --mode now`

## Reference Files to Read First
Before starting, read these to understand patterns:
- `backend/app/models/tasks.py` — model pattern
- `backend/app/models/boards.py` — board model with tenant scoping
- `backend/app/api/boards.py` — API pattern (auth, deps, CRUD)
- `backend/app/api/board_webhooks.py` — existing webhook handler (where you add the hook)
- `backend/app/core/config.py` — where to add CHANNELS_ENABLED
- `frontend/src/components/tasks/TaskList.tsx` — frontend pattern
