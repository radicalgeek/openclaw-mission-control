# Platform Board Plan

## Overview

One board per organization can be designated as the **platform board** (the
devops / infrastructure team). This board gains an extra default channel called
**Support**. All other board leads in the gateway are auto-subscribed to this
channel so they can open support threads for infrastructure requests. The
platform board lead triages these, creates tasks from threads, and resolution
notifications flow back to the requester.

---

## Work Package 1 — Backend Model: `is_platform` flag

### Changes

| File | Change |
|------|--------|
| `backend/app/models/boards.py` | Add `is_platform: bool = Field(default=False, index=True)` |
| `backend/app/schemas/boards.py` | Add `is_platform: bool = False` to `BoardBase` (inherited by `BoardCreate`, `BoardUpdate`, `BoardRead`) |
| `backend/migrations/versions/` | New Alembic revision: `ADD COLUMN is_platform BOOLEAN NOT NULL DEFAULT FALSE` |

### Uniqueness enforcement (API layer)

In `POST /boards` and `PATCH /boards/{id}`: when `is_platform=True`, query for
any **other** board in the same org with `is_platform=True`. If one exists,
return **409 Conflict**:

```
"Only one platform board is allowed per organization.
 Board '{name}' is currently the platform board."
```

### Design decision

> **Why a separate `is_platform` bool instead of `board_type = "platform"`?**
>
> `board_type` controls workflow shape (goal vs general). A platform board can
> be either a goal board or a general board. Orthogonal concerns deserve
> orthogonal fields.

---

## Work Package 2 — Support Channel: Default Channel for Platform Boards

### New channel definition

In `backend/app/services/channel_lifecycle.py`:

```python
_PLATFORM_SUPPORT_CHANNEL = _ChannelDef(
    name="Support",
    slug="support",
    channel_type="discussion",
    description="Cross-board support requests for the platform/infrastructure team",
    is_readonly=False,
    webhook_source_filter=None,
    position=9,  # after the existing 9 defaults (positions 0-8)
)
```

### Modified hook: `on_board_created()`

After creating the standard 9 channels, check `board.is_platform`. If true,
also create the Support channel and subscribe the lead to it.

### New hook: `on_board_marked_platform()`

When an existing board is toggled to `is_platform=True` via `PATCH /boards/{id}`:

1. Create the Support channel if it doesn't already exist on that board.
2. Subscribe the board's lead agent.
3. Subscribe all other gateway board leads (see WP 3).

### New hook: `on_board_unmarked_platform()`

When toggled off:

- **Archive** the Support channel (soft-delete via `is_archived=True`). Don't
  destroy historical threads.
- Remove cross-board subscriptions that were created for it.

### Call site

In `backend/app/api/boards.py` — `update_board()` endpoint: detect
`is_platform` field change and call the appropriate hook.

---

## Work Package 3 — Cross-Board Lead Subscriptions

### Why this works out of the box

`ChannelSubscription` is `(channel_id, agent_id)` with FKs to `channels.id`
and `agents.id` — no board-scoping constraint. The subscription upsert API
(`PUT /channels/{id}/subscriptions/{agent_id}`) also has no board check. This
means cross-board subscriptions work with **zero model changes**.

### New function: `sync_platform_support_subscribers()`

In `backend/app/services/channel_lifecycle.py`:

```python
async def sync_platform_support_subscribers(
    session: AsyncSession,
    gateway_id: UUID,
) -> None:
    """Ensure every board lead across the gateway is subscribed to the
    platform board's Support channel."""
```

Logic:

1. Find the platform board for the gateway
   (`Board.is_platform == True AND Board.gateway_id == gateway_id`).
2. If none, return (no-op).
3. Find the Support channel on that board (`slug="support"`).
4. Find all board leads in the gateway
   (`Agent.is_board_lead == True`, boards with matching `gateway_id`).
5. For each lead not already subscribed, create
   `ChannelSubscription(notify_on="all")`.

### Call sites

| Event | Purpose |
|-------|---------|
| `on_board_created()` | New board's lead gets added to existing platform Support channel |
| `on_board_lead_changed()` | New lead inherits subscription; old lead's subscription removed |
| `on_board_marked_platform()` | All existing gateway leads get subscribed |

### Cross-board posting

When a non-platform board lead posts a thread to the Support channel, the
existing `create_channel_thread` + `dispatch_channel_message_to_agents` routing
already works — dispatches to all subscribed agents. The platform board lead is
subscribed, so they receive the message. No new routing needed.

---

## Work Package 4 — Task Status → Thread Resolution Sync

When a task linked to a thread moves to `done`, the thread must be
auto-resolved and a system message posted. This is a **requirement**, not
optional.

### Changes

| File | Change |
|------|--------|
| `backend/app/api/tasks.py` — `_finalize_updated_task()` | After commit, if `previous_status != "done"` and `task.status == "done"` and `task.thread_id is not None`: auto-resolve the thread and post a system message |
| `backend/app/api/tasks.py` — `_apply_lead_task_update()` | Same check after commit |
| `backend/app/api/threads.py` — `update_thread()` | When `is_resolved` transitions `false → true`: post a system message and dispatch to subscribers |

### New service function

In `backend/app/services/channel_lifecycle.py` (or a new
`backend/app/services/thread_resolution.py`):

```python
async def auto_resolve_thread_for_completed_task(
    session: AsyncSession,
    task: Task,
) -> None:
    """When a task moves to done, auto-resolve its linked thread and notify."""
```

Logic:

1. Load the thread via `task.thread_id`.
2. If thread is already resolved, return (idempotent).
3. Set `thread.is_resolved = True`.
4. Create a system `ThreadMessage`:
   `"Task completed — thread auto-resolved. Task: #{task.id} ({task.title})"`
5. Dispatch the system message to all subscribers via
   `dispatch_channel_message_to_agents()`.
6. Commit.

### Call sites

Both `_finalize_updated_task()` and `_apply_lead_task_update()` — after the
existing commit, check:

```python
if (
    settings.channels_enabled
    and update.previous_status != "done"
    and update.task.status == "done"
    and update.task.thread_id is not None
):
    await auto_resolve_thread_for_completed_task(session, update.task)
```

Wrapped in `try/except` so thread resolution never blocks task updates.

### Thread resolution notification (standalone)

In `update_thread()`: when `is_resolved` transitions `false → true` (whether
from auto-resolve or manual), post a system message and dispatch to
subscribers. This covers both:

- Auto-resolve from task completion
- Manual resolve by the platform lead

---

## Work Package 5 — Template Changes: Board Lead Instructions

### Template context additions

In `backend/app/services/openclaw/provisioning.py` — `_build_context()`:

```python
"is_platform_board": str(board.is_platform).lower(),
```

Additionally, `_build_context()` or `_augment_context()` needs to query for
the platform board at render time:

```python
"has_platform_board": "true" / "false",
"platform_board_name": "<name>" or "",
```

This requires a lightweight query during template rendering. The async
provisioning context already has DB session access (via
`BoardAgentLifecycleManager._augment_context()`), so this is the right place.

### Template additions in `BOARD_AGENTS.md.j2`

After the Role Contract section, add:

**For non-platform board leads** (when a platform board exists):

```jinja
{% set is_platform_board_bool = (is_platform_board | default("false") | lower) == "true" %}
{% set has_platform_board_bool = (has_platform_board | default("false") | lower) == "true" %}

{% if is_lead and not is_platform_board_bool and has_platform_board_bool %}
## Platform Support Channel
You are subscribed to the **Support** channel on the platform board
("{{ platform_board_name }}").

When you encounter infrastructure, deployment, or platform issues that your
board cannot resolve:
1. Post a new thread in the Support channel describing the issue clearly.
2. Include: what's blocked, severity, and any error details.
3. The platform team lead will triage your request and create tasks as needed.
4. You will be notified when the thread is resolved (issue addressed).

Do not wait passively — continue other work while the platform team handles
the request.
{% endif %}
```

**For platform board leads:**

```jinja
{% if is_lead and is_platform_board_bool %}
## Platform Support Channel
You manage the **Support** channel — the cross-board channel where other board
leads request infrastructure and platform help.

Triage workflow:
1. Monitor incoming threads in the Support channel.
2. For actionable requests, create a task from the thread (this links them
   bidirectionally).
3. Assign the task to the appropriate platform agent.
4. When the task is done, resolve the thread — the requesting lead will be
   notified automatically.
5. For questions that don't need a task, respond directly in the thread.

Prioritize support threads that indicate blocking issues on other boards.
{% endif %}
```

### Re-sync on platform toggle

When a board is toggled to platform (or off), agents that are already
provisioned need updated templates. The investigation confirms:

- `sync_gateway_templates()` calls `_sync_one_agent()` for every agent on
  every board in the gateway.
- `_sync_one_agent()` calls `AgentLifecycleOrchestrator.run_lifecycle()` with
  `action="update"`.
- This re-renders all templates via `_render_agent_files()` with fresh context
  from `_build_context()`.
- Files like `AGENTS.md` are **not** in the preserve list (only `SOUL.md`,
  `USER.md`, `MEMORY.md`, `IDENTITY.md` are preserved during updates).

**Therefore**: Toggling `is_platform` and then running "Sync Templates" from
the gateway admin page will propagate the new platform instructions to all
agents.

**Automatic re-sync on toggle**: The `PATCH /boards/{id}` handler should
trigger a gateway template sync for the board's gateway when `is_platform`
changes. This is a best-effort background operation:

```python
if "is_platform" in changed_fields:
    try:
        from app.services.openclaw.provisioning_db import (
            OpenClawProvisioningService,
            GatewayTemplateSyncOptions,
        )
        gateway = await session.get(Gateway, updated.gateway_id)
        if gateway:
            await OpenClawProvisioningService(session).sync_gateway_templates(
                gateway,
                GatewayTemplateSyncOptions(
                    user=None,       # will resolve to org owner
                    include_main=False,
                    lead_only=True,  # only leads need the new instructions
                    reset_sessions=False,
                    rotate_tokens=False,
                    force_bootstrap=False,
                    overwrite=False,
                ),
            )
    except Exception:
        logger.exception("board.platform_toggle.template_sync_failed board_id=%s", updated.id)
```

This ensures that when a board is marked/unmarked as platform, all lead agents
across the gateway get updated `AGENTS.md` files reflecting the new Support
channel instructions — without requiring manual intervention.

**Note**: `lead_only=True` is sufficient because:
- Only leads get the platform support instructions in `BOARD_AGENTS.md.j2`
- Worker agents don't interact with the Support channel directly
- This keeps the sync fast (one agent per board instead of all agents)

---

## Work Package 6 — Frontend: Board Config UI

### Board edit page toggle

In `frontend/src/app/boards/[boardId]/edit/page.tsx` — Rules section:

Add a "Platform board" toggle using the existing switch pattern:

- **Label**: Platform board
- **Description**: Designate this as the organization's
  platform/infrastructure board. Only one board can be the platform board. Adds
  a cross-board Support channel.
- Wire to `is_platform` field in the `BoardUpdate` payload.
- On **409** response, show a toast:
  "Only one platform board allowed — currently set on '{name}'."

### Board create page (optional, lower priority)

Optionally add the toggle to `frontend/src/app/boards/new/page.tsx`. Can be
deferred since it can be set from the edit page.

### Visual indicators

| Component | Change |
|-----------|--------|
| `BoardGoalPanel.tsx` | Show "Platform" badge when `is_platform` is true |
| `BoardsTable.tsx` | Optionally add a "Platform" badge column |
| `ChannelsLayout.tsx` | Show a visual indicator (shield icon or "cross-board" label) on the Support channel |

### API client regeneration

Run `make api-gen` after backend changes to pick up `is_platform` in the
generated TypeScript types.

---

## Work Package 7 — Tests

| Test | Description |
|------|-------------|
| API: platform board create | Creating a board with `is_platform=True` creates 10 channels (9 default + Support) |
| API: uniqueness | Setting a second board to `is_platform=True` returns 409 |
| API: un-platform | Toggling `is_platform` off archives the Support channel |
| Lifecycle: cross-board subscription | When a new board is created, its lead is subscribed to the existing platform board's Support channel |
| Lifecycle: lead change | When board lead changes, the new lead inherits the Support subscription |
| Task → Thread: auto-resolve | When a task linked to a thread moves to `done`, the thread is auto-resolved with a system message |
| Thread: resolve notification | Resolving a support thread dispatches a notification to subscribers |
| Template: non-platform lead | Non-platform lead template includes Support channel instructions when a platform board exists |
| Template: platform lead | Platform lead template includes triage instructions |
| Template: re-sync on toggle | Toggling `is_platform` triggers gateway template sync for all leads |

---

## Implementation Order

| Phase | Work Packages | Description |
|-------|---------------|-------------|
| 1 | WP 1 | Model, migration, uniqueness check |
| 2 | WP 2 + WP 3 | Support channel creation + cross-board subscriptions |
| 3 | WP 4 | Task status → thread resolution sync |
| 4 | WP 5 | Template changes + auto re-sync on toggle |
| 5 | WP 6 | Frontend toggle and badges |
| 6 | WP 7 | Tests (written alongside each phase) |

---

## Key Design Decisions & Risks

### 1. Cross-board subscriptions — zero model changes

The `ChannelSubscription` model already supports `(channel_id, agent_id)` with
no board-scoping constraint. The subscription API also has no board check. This
means cross-board subscriptions work without any schema migration.

### 2. No new notification system

Thread resolution notifications piggyback on the existing
`dispatch_channel_message_to_agents` pathway. A system message posted when a
thread is resolved is dispatched to all subscribers, including the cross-board
lead who opened the thread.

### 3. Soft-delete on un-platform

Archiving the Support channel (`is_archived=True`) rather than hard-deleting
preserves thread history if a board is toggled off and back on.

### 4. Template re-sync on platform toggle

When `is_platform` changes, a gateway template sync is triggered automatically
for all lead agents. This ensures already-provisioned agents get the updated
`AGENTS.md` with platform support instructions without manual intervention.

The sync only targets leads (`lead_only=True`) since worker agents don't
interact with the Support channel and don't need the instructions.

### 5. Task → thread auto-resolve is required

When a task linked to a thread moves to `done`, the thread is auto-resolved
with a system message dispatched to all subscribers. This closes the loop for
the requesting board lead — they know their support request was handled without
having to poll the thread.
