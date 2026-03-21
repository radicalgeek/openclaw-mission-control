# Mission Control Channels: Agent Implementation Plan

> **Project**: Add Zulip-style channel-based messaging to OpenClaw Mission Control
> **Repository**: `radicalgeek/openclaw-mission-control` (fork of `abhi1693/openclaw-mission-control`)
> **Architecture**: Next.js frontend + Python backend + OpenClaw Gateway (WebSocket)

---

## Critical Architectural Decision: The Unified Thread Model

### The Problem

Webhook events (build failures, deployment alerts, test results) can appear both as:
1. A **task/ticket on a board** (the existing system)
2. A **message in an alert channel** (the new system)

If these are separate data paths, you get duplication: the same build failure appears as a board ticket AND a channel message, with comments on each living in different places. Users and agents end up having the same conversation in two locations.

### The Solution: Single Source of Truth with Dual Presentation

Every webhook event and every conversation exists as a **thread**. A thread is the atomic unit. The board task view and the channel message view are two *lenses* onto the same underlying data.

**Critically, Mission Control already has webhooks that create tasks/issues on the board.** The channel system does NOT duplicate this. Instead, the existing webhook pipeline remains the authority for task creation. When a webhook creates a task, the channel system simultaneously creates a linked thread in the appropriate alert channel. The task and the thread share the same message history from that point forward.

```
                    EXISTING WEBHOOK ARRIVES
                            │
                            ▼
              ┌─────────────────────────┐
              │  Existing webhook       │
              │  handler creates TASK   │  ← This already works today
              │  on the board           │
              └────────────┬────────────┘
                           │
                    NEW: post-create hook
                           │
                           ▼
              ┌─────────────────────────┐
              │  Channel system creates │
              │  a THREAD in the        │  ← New behaviour
              │  matching alert channel │
              │  and links it to the    │
              │  task via task_id       │
              └────────────┬────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              THREAD (linked to task)                     │
│                                                         │
│  thread_id: "thr_abc123"                                │
│  channel_id: "chan_build_alerts"                         │
│  topic: "api-service/main — Build #1234"                │
│  task_id: "task_456" ◄── linked to existing task        │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ MESSAGES (shared by both views)                 │    │
│  │                                                 │    │
│  │  [webhook]  Build #1234 FAILED on main          │    │
│  │  [user]     @devops-agent what broke?           │    │
│  │  [agent]    The test suite in /api/auth failed  │    │
│  │  [user]     Can you fix it?                     │    │
│  │  [agent]    Created PR #89 with the fix         │    │
│  │  [webhook]  Build #1235 PASSED on main          │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Viewed in Channel: shows as topic thread               │
│  Viewed on Board: shows as task with comment history    │
└─────────────────────────────────────────────────────────┘
```

**Rules:**
- A thread ALWAYS belongs to a channel.
- A thread MAY be linked to a board task (via `task_id`).
- The **existing webhook system creates tasks** as it does today. The channel system hooks into task creation to also create a linked thread in the appropriate channel. It does NOT create tasks itself — that would cause duplication.
- For discussion channels (not webhook-driven), users create threads directly. These may optionally be linked to a task, but don't have to be.
- Comments on the board task are messages on the thread. Messages on the thread appear as comments on the task. They are the SAME records.
- Agent responses go to the thread. Both views see them.

This eliminates duplication entirely. The existing webhook → task pipeline is untouched. The channel system is an observer that enriches tasks with a conversation thread and provides an alternative view.

---

## Work Packages

This plan is divided into 8 work packages (WP). Each is self-contained with clear inputs, outputs, acceptance criteria, and the files that need to be created or modified. Packages can be worked in parallel where indicated.

---

## WP-1: Database Schema & Migrations

**Purpose**: Define the data model for channels, threads, and messages.
**Dependencies**: None (start here)
**Estimated effort**: 2–3 days

### 1.1 New Models

Create these in the backend models directory, following the existing patterns for Board, Task, etc.

#### Channel

```python
# Location: backend/src/models/channel.py (or wherever models live in your fork)

class Channel:
    id: str              # UUID, primary key
    board_id: str        # FK to Board — each board has its own set of channels
    name: str            # e.g., "Build Alerts", "Development"
    slug: str            # URL-safe: "build-alerts", "development"
    channel_type: str    # "alert" or "discussion"
    description: str     # Optional description shown in UI
    is_archived: bool    # Soft delete / hide
    is_readonly: bool    # If true, only webhooks and agents can post (no user messages)
    webhook_source_filter: str | None  # For alert channels: which webhook sources route here
                                       # e.g., "build", "deployment", "test", "production"
                                       # Used by the task-creation hook to pick the right channel
                                       # NULL for discussion channels
    webhook_secret: str  # Per-channel secret for authenticating direct channel webhooks (optional secondary path)
    position: int        # Sort order within the board's channel list
    created_at: datetime
    updated_at: datetime
```

#### Thread

```python
# Location: backend/src/models/thread.py

class Thread:
    id: str              # UUID, primary key
    channel_id: str      # FK to Channel
    topic: str           # The topic/subject line (Zulip-style)
    task_id: str | None  # FK to Task (nullable) — the linked board task
    source_type: str     # "user", "webhook", "agent", "system"
    source_ref: str | None  # External reference (e.g., GitHub run ID, deployment ID)
    is_resolved: bool    # Can be marked resolved (hides from active view)
    is_pinned: bool      # Pinned threads stay at top of channel
    message_count: int   # Denormalised count for performance
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # Unique constraint: (channel_id, source_type, source_ref) — prevents duplicate webhook threads
```

#### ThreadMessage

```python
# Location: backend/src/models/thread_message.py

class ThreadMessage:
    id: str              # UUID, primary key
    thread_id: str       # FK to Thread
    sender_type: str     # "user", "agent", "webhook", "system"
    sender_id: str | None  # FK to User or Agent (nullable for webhooks/system)
    sender_name: str     # Display name (resolved at write time for stable display)
    content: str         # Message body (Markdown)
    content_type: str    # "text", "webhook_event", "agent_response", "system_notification"
    metadata: dict       # JSON — webhook payload, agent context, structured data for card rendering
    is_edited: bool
    created_at: datetime
    updated_at: datetime
```

#### ChannelSubscription

```python
# Location: backend/src/models/channel_subscription.py

class ChannelSubscription:
    id: str              # UUID, primary key
    channel_id: str      # FK to Channel
    agent_id: str        # FK to Agent
    notify_on: str       # "all", "mentions", "none"
    created_at: datetime
```

#### UserChannelState

```python
# Location: backend/src/models/user_channel_state.py

class UserChannelState:
    id: str              # UUID, primary key
    user_id: str         # FK to User
    channel_id: str      # FK to Channel
    last_read_message_id: str | None  # FK to ThreadMessage — for unread tracking
    is_muted: bool
    updated_at: datetime

    # Unique constraint: (user_id, channel_id)
```

### 1.2 Default Channel Seeding

When a Board is created (or for existing boards via a one-time migration), auto-create these channels:

**Alert channels** (type: "alert", is_readonly: true, webhook_source_filter set):
| Name | Slug | webhook_source_filter | Description |
|---|---|---|---|
| Build Alerts | build-alerts | build | CI/CD build results and failures |
| Deployment Alerts | deployment-alerts | deployment | Deployment status and rollback notifications |
| Test Run Alerts | test-run-alerts | test | Test suite results and coverage changes |
| Production Alerts | production-alerts | production | Production incidents, errors, and health checks |

**Discussion channels** (type: "discussion", is_readonly: false, webhook_source_filter: null):
| Name | Slug | Description |
|---|---|---|
| Development | development | Code discussions, feature planning, technical decisions |
| DevOps | devops | Infrastructure, pipelines, and operational topics |
| Testing | testing | Test strategy, QA discussions, bug triage |
| Architecture | architecture | System design, ADRs, and architectural decisions |
| General | general | Anything that doesn't fit elsewhere |

### 1.3 Board Lifecycle Hooks — Channel Groups Follow Boards

The channels page shows each board as a group (a collapsible section containing that board's channels). This means the channel structure MUST stay in sync with board CRUD. Channels are children of boards, so this is enforced by the data model, but the lifecycle hooks ensure the full setup and teardown happen automatically.

#### On Board Created

Hook into the existing board creation path. After a board is persisted:

```python
# Location: backend/src/services/channel_lifecycle.py

def on_board_created(board: Board):
    """
    Called immediately after a new Board is created.
    Creates the full default channel set for the board.
    """
    default_channels = get_default_channel_definitions()  # Returns the tables above

    for channel_def in default_channels:
        channel = Channel(
            board_id=board.id,
            name=channel_def.name,
            slug=channel_def.slug,
            channel_type=channel_def.channel_type,
            description=channel_def.description,
            is_readonly=channel_def.is_readonly,
            webhook_source_filter=channel_def.webhook_source_filter,
            webhook_secret=generate_webhook_secret(),
            position=channel_def.position,
        )
        db.add(channel)

    db.flush()  # Ensure channel IDs are available

    # Subscribe the board's lead agent to ALL channels
    channels = Channel.query.filter_by(board_id=board.id).all()
    for channel in channels:
        if board.lead_agent_id:
            db.add(ChannelSubscription(
                channel_id=channel.id,
                agent_id=board.lead_agent_id,
                notify_on="all",
            ))

    db.commit()
```

**Where to hook this in**: Find the existing board creation endpoint (likely in `backend/src/api/boards.py` or the board service layer). Add a call to `on_board_created(board)` immediately after the board is committed to the database. Same pattern as the WP-4 webhook hook — wrap in try/except so board creation never fails because of a channel error.

#### On Board Deleted / Archived

When a board is removed, its entire channel group must go with it:

```python
def on_board_deleted(board: Board, hard_delete: bool = False):
    """
    Called when a Board is deleted or archived.
    Cascades to all channels, threads, messages, and subscriptions.
    """
    channels = Channel.query.filter_by(board_id=board.id).all()

    if hard_delete:
        # Hard delete: remove all channel data
        # Order matters for FK constraints: messages → threads → subscriptions → state → channels
        for channel in channels:
            ThreadMessage.query.filter(
                ThreadMessage.thread_id.in_(
                    Thread.query.filter_by(channel_id=channel.id).with_entities(Thread.id)
                )
            ).delete(synchronize_session=False)
            Thread.query.filter_by(channel_id=channel.id).delete()
            ChannelSubscription.query.filter_by(channel_id=channel.id).delete()
            UserChannelState.query.filter_by(channel_id=channel.id).delete()

        Channel.query.filter_by(board_id=board.id).delete()
    else:
        # Soft delete: archive all channels (preserves history)
        for channel in channels:
            channel.is_archived = True

    db.commit()
```

**Where to hook this in**: Find the existing board deletion/archive endpoint. Add a call to `on_board_deleted(board)` BEFORE the board itself is deleted (so FK lookups still work).

#### On Board Agent Changed

When the board's lead agent changes, or when agents are added/removed from a board:

```python
def on_board_lead_changed(board: Board, old_lead_id: str | None, new_lead_id: str):
    """Update channel subscriptions when the board lead changes."""
    channels = Channel.query.filter_by(board_id=board.id, is_archived=False).all()

    for channel in channels:
        # Remove old lead's auto-subscription (if they had one)
        if old_lead_id:
            ChannelSubscription.query.filter_by(
                channel_id=channel.id, agent_id=old_lead_id
            ).delete()

        # Add new lead's subscription to all channels
        existing = ChannelSubscription.query.filter_by(
            channel_id=channel.id, agent_id=new_lead_id
        ).first()
        if not existing:
            db.add(ChannelSubscription(
                channel_id=channel.id,
                agent_id=new_lead_id,
                notify_on="all",
            ))

    db.commit()

def on_agent_added_to_board(board: Board, agent_id: str):
    """Subscribe a newly added agent to the board's discussion channels with mentions-only."""
    channels = Channel.query.filter_by(
        board_id=board.id, channel_type="discussion", is_archived=False
    ).all()

    for channel in channels:
        existing = ChannelSubscription.query.filter_by(
            channel_id=channel.id, agent_id=agent_id
        ).first()
        if not existing:
            db.add(ChannelSubscription(
                channel_id=channel.id,
                agent_id=agent_id,
                notify_on="mentions",
            ))

    db.commit()

def on_agent_removed_from_board(board: Board, agent_id: str):
    """Remove all channel subscriptions for an agent leaving the board."""
    channel_ids = [c.id for c in Channel.query.filter_by(board_id=board.id).all()]
    ChannelSubscription.query.filter(
        ChannelSubscription.channel_id.in_(channel_ids),
        ChannelSubscription.agent_id == agent_id,
    ).delete(synchronize_session=False)
    db.commit()
```

### 1.4 Migration for Existing Boards

Write a migration that:
1. Creates the new tables.
2. Iterates all existing Boards and runs `on_board_created()` for each (creating default channels and subscriptions).
3. Skips archived/deleted boards (or archives their channels too).

### 1.5 Task ↔ Thread Linking (for existing tasks)

Add a nullable `thread_id` column to the existing Task model. Existing tasks will have `thread_id = NULL`. New tasks created via the channel system will have a linked thread. The board task comment system should be updated to read/write from ThreadMessage when a task has a linked thread (see WP-5).

### Acceptance Criteria
- [ ] All models created with proper indexes (channel_id, thread_id, created_at for message queries)
- [ ] Migration runs cleanly on a fresh database AND on a database with existing boards/tasks
- [ ] Default channels are created for all existing boards
- [ ] Agent subscriptions are seeded correctly
- [ ] Creating a new board auto-creates the full channel group with subscriptions
- [ ] Deleting/archiving a board cascades to archive all its channels
- [ ] Changing the board lead updates channel subscriptions
- [ ] Adding/removing an agent from a board updates channel subscriptions
- [ ] `pytest` passes for model creation, relationships, lifecycle hooks, and constraints

---

## WP-2: Backend API Endpoints

**Purpose**: Create the REST API for channels, threads, and messages.
**Dependencies**: WP-1
**Estimated effort**: 3–4 days

### 2.1 Channel Endpoints

```
GET    /api/boards/{board_id}/channels
       → Returns list of channels for a board, with unread counts per channel for the authenticated user
       → Response includes: channel object + unread_count (int) + last_message_preview (string)

GET    /api/channels/{channel_id}
       → Returns channel details including subscription info

PATCH  /api/channels/{channel_id}
       → Update channel properties (name, description, is_readonly, auto_create_tasks, position)
       → Only board admins / org admins

POST   /api/boards/{board_id}/channels
       → Create a custom channel on a board
       → Body: { name, channel_type, description, is_readonly, auto_create_tasks }

DELETE /api/channels/{channel_id}
       → Archives a channel (soft delete — sets is_archived = true)
       → Does NOT delete messages
```

### 2.2 Thread Endpoints

```
GET    /api/channels/{channel_id}/threads
       → Returns threads in a channel, sorted by last_message_at DESC
       → Query params: ?resolved=false (default), ?pinned_first=true (default)
       → Response includes: thread object + message_count + last_message preview + linked task summary

GET    /api/threads/{thread_id}
       → Returns thread with full details including linked task info

POST   /api/channels/{channel_id}/threads
       → Create a new thread (user-initiated conversation)
       → Body: { topic, content (first message) }
       → If channel.auto_create_tasks is true, also creates a linked Task on the board

PATCH  /api/threads/{thread_id}
       → Update thread (resolve, pin, rename topic)
       → Body: { is_resolved?, is_pinned?, topic? }

POST   /api/threads/{thread_id}/link-task
       → Manually link a thread to an existing board task
       → Body: { task_id }
       → Validation: task must be on the same board as the thread's channel

POST   /api/threads/{thread_id}/unlink-task
       → Remove the task link (does not delete the task or thread)
```

### 2.3 Message Endpoints

```
GET    /api/threads/{thread_id}/messages
       → Returns messages in a thread, sorted by created_at ASC
       → Pagination: ?before={message_id}&limit=50
       → This is the SINGLE SOURCE for both channel view and board task comment view

POST   /api/threads/{thread_id}/messages
       → Send a message to a thread
       → Body: { content, content_type? (default "text") }
       → Side effects:
         - Updates thread.last_message_at and thread.message_count
         - Dispatches to Gateway for agent processing (see WP-3)
         - Updates unread state for other users viewing this channel

PATCH  /api/messages/{message_id}
       → Edit a message (own messages only, or admin)
       → Body: { content }
       → Sets is_edited = true

DELETE /api/messages/{message_id}
       → Soft-delete a message (own messages only, or admin)
```

### 2.4 Subscription & State Endpoints

```
GET    /api/channels/{channel_id}/subscriptions
       → List agent subscriptions for a channel

PUT    /api/channels/{channel_id}/subscriptions/{agent_id}
       → Create or update an agent's subscription to a channel
       → Body: { notify_on: "all" | "mentions" | "none" }

DELETE /api/channels/{channel_id}/subscriptions/{agent_id}
       → Remove an agent's subscription

POST   /api/channels/{channel_id}/mark-read
       → Mark all messages in a channel as read for the authenticated user
       → Updates UserChannelState.last_read_message_id to the latest message

POST   /api/channels/{channel_id}/mute
       → Toggle mute for the authenticated user on this channel
```

### 2.5 Search Endpoint

```
GET    /api/boards/{board_id}/channels/search
       → Full-text search across all channel messages on a board
       → Query params: ?q=search+term&channel_id=...&sender_type=...&after=...&before=...
       → Returns messages with thread context (channel name, topic)
```

### 2.6 Unread Count Calculation

The unread count for a channel is calculated as:

```sql
SELECT COUNT(*) FROM thread_message tm
JOIN thread t ON tm.thread_id = t.id
WHERE t.channel_id = :channel_id
  AND tm.created_at > (
    SELECT COALESCE(
      (SELECT tm2.created_at FROM thread_message tm2 WHERE tm2.id = ucs.last_read_message_id),
      '1970-01-01'
    )
    FROM user_channel_state ucs
    WHERE ucs.user_id = :user_id AND ucs.channel_id = :channel_id
  )
```

For performance, consider denormalising this into `UserChannelState.unread_count` and updating it via triggers or application-level hooks.

### Acceptance Criteria
- [ ] All endpoints implemented with proper auth checks
- [ ] Input validation using existing validation patterns (Pydantic/Zod schemas)
- [ ] Pagination works correctly for messages and threads
- [ ] Unread counts are accurate
- [ ] API tests cover happy paths and error cases (missing channel, wrong board, permission denied)
- [ ] OpenAPI schema / generated client updated to include new endpoints

---

## WP-3: Agent Message Routing via Gateway

**Purpose**: Wire channel messages to agents through the OpenClaw Gateway WebSocket.
**Dependencies**: WP-1, WP-2
**Estimated effort**: 3–4 days

### 3.1 How Board Chat Works Today (Reference)

Currently, when a user sends a message in board chat:
1. Frontend sends message to backend API
2. Backend dispatches to OpenClaw Gateway via WebSocket (port 18789)
3. Gateway routes to the board's lead agent session
4. Agent processes and responds via Gateway WebSocket
5. Backend receives response, stores it, pushes to frontend via existing real-time mechanism

### 3.2 Channel Message Dispatch Flow

When a user posts a message in a channel thread:

```
User posts message in thread
         │
         ▼
Backend receives POST /api/threads/{id}/messages
         │
         ├─── Store message in ThreadMessage table
         │
         ├─── Broadcast to connected frontends via WebSocket/SSE
         │    (so other users viewing this thread see it immediately)
         │
         └─── Dispatch to Gateway with channel context
              │
              ▼
         Gateway message envelope (extended):
         {
           "type": "channel_message",
           "board_id": "...",
           "channel_id": "...",
           "channel_name": "Development",
           "thread_id": "...",
           "topic": "API redesign discussion",
           "message": {
             "id": "...",
             "content": "@architecture-agent should we use REST or GraphQL?",
             "sender_name": "User",
             "sender_type": "user"
           },
           "context": {
             "recent_messages": [...],  // Last N messages in this thread for context
             "thread_summary": "...",    // Optional summary if thread is long
             "mentioned_agents": ["architecture-agent"],
             "channel_subscriptions": {
               "architecture-agent": "all",
               "devops-agent": "mentions"
             }
           }
         }
```

### 3.3 Agent Routing Logic

The backend determines which agents to notify based on:

```python
def get_agents_to_notify(thread_id: str, message_content: str) -> list[AgentNotification]:
    thread = get_thread(thread_id)
    channel = get_channel(thread.channel_id)
    board = get_board(channel.board_id)
    subscriptions = get_channel_subscriptions(channel.id)

    notifications = []

    for sub in subscriptions:
        should_notify = False

        # Board lead always gets notified
        if sub.agent_id == board.lead_agent_id:
            should_notify = True

        # "all" subscribers get every message
        elif sub.notify_on == "all":
            should_notify = True

        # "mentions" subscribers only get notified if @mentioned
        elif sub.notify_on == "mentions":
            if is_agent_mentioned(message_content, sub.agent_id):
                should_notify = True

        if should_notify:
            notifications.append(AgentNotification(
                agent_id=sub.agent_id,
                is_lead=sub.agent_id == board.lead_agent_id,
                is_mentioned=is_agent_mentioned(message_content, sub.agent_id),
            ))

    return notifications
```

### 3.4 Agent Response Handling

When an agent responds via the Gateway:

```python
def handle_agent_response(gateway_event):
    # Extract thread context from the response
    thread_id = gateway_event["thread_id"]
    agent_id = gateway_event["agent_id"]
    content = gateway_event["content"]

    # Store as a ThreadMessage
    message = create_thread_message(
        thread_id=thread_id,
        sender_type="agent",
        sender_id=agent_id,
        sender_name=get_agent_display_name(agent_id),
        content=content,
        content_type="agent_response",
    )

    # Broadcast to frontends
    broadcast_new_message(thread_id, message)

    # Update unread counts for users not currently viewing this thread
    update_unread_counts(thread_id, message.id)
```

### 3.5 Gateway Envelope Extension

If the current Gateway message format doesn't support a `thread_id` and `channel_id` field, you have two options:

**Option A (Preferred)**: Extend the Gateway envelope. Add `thread_id` and `channel_id` to the WebSocket message schema. This requires a change to the Gateway or your fork's handling of Gateway messages.

**Option B (Pragmatic fallback)**: Use the existing board chat mechanism but tag messages with channel/thread metadata in a `metadata` JSON field that the Gateway passes through transparently. The backend extracts this on the response side.

### 3.6 Context Window Management

Agents have limited context windows. When dispatching a channel message to an agent:

1. Include the last 20 messages from the thread (not the entire history)
2. If the thread has more than 20 messages, include a one-paragraph summary of the earlier conversation (generated by the lead agent or a background summarisation job)
3. Include a brief description of the channel purpose so the agent knows the conversational context
4. For @mentioned agents who don't follow the channel, include a brief "You were mentioned in #{channel_name} > {topic}" preamble

### Acceptance Criteria
- [ ] User message in a channel thread reaches the board lead agent
- [ ] @mentioned agents receive the message with correct context
- [ ] Agent responses are stored as ThreadMessages and appear in both channel and board task views
- [ ] Context window includes recent thread history (not full history)
- [ ] If Gateway doesn't support extended envelope, fallback metadata approach works
- [ ] End-to-end test: user sends message → agent responds → response appears in UI

---

## WP-4: Hooking Into the Existing Webhook → Task Pipeline

**Purpose**: When the existing webhook system creates a task on the board, automatically create a linked thread in the appropriate alert channel so the conversation lives in both places.
**Dependencies**: WP-1, WP-2
**Estimated effort**: 3–4 days

### 4.1 Core Principle: The Existing Pipeline Is the Authority

Mission Control already has webhooks that create issues/tasks on the board. **This must not change.** The channel system is a downstream observer that enriches task creation, not a replacement for it.

The integration point is a **post-create hook** on the existing task creation path. When a task is created by a webhook, the hook:
1. Determines which alert channel the task belongs to (based on webhook source/type)
2. Creates a Thread in that channel, linked to the task
3. Creates an initial ThreadMessage with the webhook payload as a structured event
4. The task and thread are now linked — all subsequent comments/messages are shared

```
┌────────────────────────────────┐
│  External service fires        │
│  webhook to Mission Control    │
└──────────────┬─────────────────┘
               │
               ▼
┌────────────────────────────────┐
│  EXISTING webhook handler      │
│  (board webhook endpoint)      │  ← UNCHANGED
│  Creates task on the board     │
└──────────────┬─────────────────┘
               │
               ▼  NEW: post-task-creation hook
┌────────────────────────────────┐
│  channel_thread_hook()         │
│                                │
│  1. Classify webhook source    │
│     (build / deploy / test /   │
│      production / other)       │
│                                │
│  2. Find matching channel      │
│     on the board by            │
│     webhook_source_filter      │
│                                │
│  3. Create Thread linked to    │
│     the task                   │
│                                │
│  4. Create initial             │
│     ThreadMessage with         │
│     webhook event data         │
│                                │
│  5. Set task.thread_id         │
└────────────────────────────────┘
```

### 4.2 The Post-Creation Hook

This is the central piece. It fires after ANY task is created by a webhook (not manually created tasks).

```python
# Location: backend/src/services/channel_thread_hook.py

def on_task_created_by_webhook(
    task: Task,
    board: Board,
    webhook_payload: dict,
    webhook_headers: dict,
):
    """
    Called by the existing webhook handler AFTER a task has been created.
    Creates a linked thread in the appropriate alert channel.
    
    This function must be safe to fail — if channel creation fails,
    the task is still valid. Log the error and move on.
    """
    try:
        # 1. Classify the webhook source
        event = classify_webhook_event(webhook_payload, webhook_headers)

        # 2. Find the matching alert channel on this board
        channel = find_channel_for_event(board.id, event.source_category)
        if not channel:
            # No matching channel configured — nothing to do
            return

        # 3. Deduplicate: check if a thread already exists for this source_ref
        existing_thread = Thread.query.filter_by(
            channel_id=channel.id,
            source_ref=event.source_ref,
        ).first()

        if existing_thread:
            # Thread already exists (e.g., webhook retry or related event)
            # Just append a new message to the existing thread
            thread = existing_thread
            # Also link the task if not already linked
            if not existing_thread.task_id:
                existing_thread.task_id = task.id
        else:
            # 4. Create new thread
            thread = Thread(
                channel_id=channel.id,
                topic=event.topic,
                source_type="webhook",
                source_ref=event.source_ref,
                task_id=task.id,
            )
            db.add(thread)

        # 5. Create the initial webhook event message
        message = ThreadMessage(
            thread_id=thread.id,
            sender_type="webhook",
            sender_name=event.source,
            content=event.content_markdown,
            content_type="webhook_event",
            metadata=event.metadata,
        )
        db.add(message)

        # 6. Link the task back to the thread
        task.thread_id = thread.id
        db.commit()

        # 7. Broadcast to connected frontends
        broadcast_new_thread(channel.id, thread, message)

        # 8. Notify subscribed agents if severity warrants it
        if event.severity in ("error", "critical"):
            dispatch_to_agents(thread, message)

    except Exception as e:
        logger.error(f"Channel thread hook failed for task {task.id}: {e}")
        # Do NOT re-raise — the task creation must succeed even if the channel hook fails
```

### 4.3 Webhook Event Classification

The classifier determines which channel a webhook event belongs to. This maps webhook payloads to the `webhook_source_filter` values on channels.

```python
# Location: backend/src/webhooks/classifier.py

class ClassifiedEvent:
    source: str             # "github-actions", "gitlab-ci", "argocd", etc.
    source_category: str    # "build", "deployment", "test", "production" — matches channel filter
    event_type: str         # "build_success", "build_failure", "deployment_started", etc.
    topic: str              # Thread topic (e.g., "api-service/main — Build #1234")
    source_ref: str         # Unique external ID for deduplication
    summary: str            # Human-readable one-line summary
    content_markdown: str   # Full message in Markdown
    metadata: dict          # Raw payload + parsed fields for card rendering
    severity: str           # "info", "warning", "error", "critical"
    url: str | None         # Link to external source

def classify_webhook_event(payload: dict, headers: dict) -> ClassifiedEvent:
    """
    Try each classifier in order. First match wins.
    """
    classifiers = [
        GitHubActionsClassifier(),
        GitHubPRClassifier(),
        GitLabCIClassifier(),
        DeploymentClassifier(),
        TestResultsClassifier(),
        GenericClassifier(),  # Always matches — fallback
    ]
    for classifier in classifiers:
        if classifier.can_classify(headers, payload):
            return classifier.classify(headers, payload)

def find_channel_for_event(board_id: str, source_category: str) -> Channel | None:
    """Find the alert channel on this board that matches the source category."""
    return Channel.query.filter_by(
        board_id=board_id,
        webhook_source_filter=source_category,
        is_archived=False,
    ).first()
```

### 4.4 Built-In Classifiers

Each classifier determines the `source_category` which maps to a channel's `webhook_source_filter`.

#### GitHub Actions → source_category: "build"

```python
class GitHubActionsClassifier:
    """
    Matches: X-GitHub-Event header = "workflow_run" or "check_suite"
    source_category: "build"
    Topic format: "{repo}/{workflow} — Run #{run_number}"
    source_ref: "github:workflow_run:{run_id}"
    severity: "info" for success, "error" for failure, "warning" for cancelled
    """
```

#### Deployment events → source_category: "deployment"

```python
class DeploymentClassifier:
    """
    Matches: X-GitHub-Event = "deployment" / "deployment_status",
             or payload contains "deployment"/"deploy" key,
             or X-Webhook-Source matches known CD tools (ArgoCD, Flux, etc.)
    source_category: "deployment"
    Topic format: "{service} — {environment} @ {version}"
    source_ref: "deploy:{service}:{environment}:{deployment_id}"
    """
```

#### Test results → source_category: "test"

```python
class TestResultsClassifier:
    """
    Matches: payload contains "test"/"suite"/"coverage" keys,
             or X-GitHub-Event = "check_run" with test-related naming
    source_category: "test"
    Topic format: "{suite_name} — {timestamp}"
    source_ref: "test:{suite}:{run_id or timestamp}"
    """
```

#### GitHub PRs → source_category: "build" (or configurable)

```python
class GitHubPRClassifier:
    """
    Matches: X-GitHub-Event = "pull_request"
    source_category: "build" (PRs are part of the build/development cycle)
    Topic format: "{repo} — PR #{number}: {title}"
    source_ref: "github:pr:{repo}:{number}"
    """
```

#### Generic fallback → source_category: "production"

```python
class GenericClassifier:
    """
    Always matches. Catches everything the specific classifiers don't.
    source_category: "production" (safe default — unknown alerts go to production channel)
    Topic format: "{source or 'Alert'} — {timestamp}"
    source_ref: hash of payload
    """
```

### 4.5 Hooking Into the Existing Webhook Handler

The key integration task: find the existing webhook handler code in the Mission Control backend and add a call to `on_task_created_by_webhook()` after the task is created.

**What to look for in the codebase:**
- The existing webhook endpoint (likely in `backend/src/api/webhooks.py` or similar)
- The function that creates a Task from a webhook payload
- Add the hook call immediately after `db.commit()` for the new task

```python
# In the EXISTING webhook handler (pseudo-code showing where to add the hook)

def handle_board_webhook(board_id: str, payload: dict, headers: dict):
    # ... existing validation ...
    # ... existing task creation ...
    task = create_task(board_id=board_id, title=..., ...)
    db.commit()

    # ──── NEW: Channel thread hook ────
    from services.channel_thread_hook import on_task_created_by_webhook
    board = get_board(board_id)
    on_task_created_by_webhook(task, board, payload, headers)
    # ──────────────────────────────────

    return task
```

**Critical**: The hook must be wrapped in a try/except so webhook processing never fails because of a channel system error. The task creation is the priority.

### 4.6 Subsequent Webhook Events for the Same Source

When a follow-up webhook arrives for something already tracked (e.g., a build that was failing now passes):

1. The existing webhook handler may create a NEW task, or update the existing one — this depends on the current Mission Control behaviour.
2. The channel hook uses `source_ref` deduplication: if a thread with the same `source_ref` exists, it appends a new message rather than creating a new thread.
3. This means a single thread might accumulate: "Build FAILED" → user conversation → "Build PASSED", giving a complete narrative.

### 4.7 Direct Channel Webhooks (Secondary Path)

In addition to the primary path (existing webhooks → tasks → threads), channels also support direct webhook endpoints for services that should post to a channel WITHOUT creating a board task. This is useful for informational events (successful builds, routine deployments) that don't need to be tracked as tasks.

```
POST /api/channels/{channel_id}/webhook
     Headers: X-Webhook-Secret: {channel.webhook_secret}
     Body: raw JSON payload
```

This endpoint:
1. Validates the webhook secret
2. Classifies the event using the same classifier pipeline
3. Finds or creates a thread (deduplication via source_ref)
4. Creates a ThreadMessage — but does NOT create a task
5. The thread has `task_id = NULL` (it's a channel-only conversation)

This gives users two webhook paths:
- **Board webhook** (existing): Creates task + thread (full tracking)
- **Channel webhook** (new): Creates thread only (visibility without task overhead)

### 4.8 Webhook Configuration UI Data

Each channel exposes its direct webhook URL and secret:

```
Webhook URL: https://{your-domain}/api/channels/{channel_id}/webhook
Secret: {channel.webhook_secret}
```

Regenerate the secret:

```
POST /api/channels/{channel_id}/regenerate-webhook-secret
     → Returns new secret, invalidates old one
```

### Acceptance Criteria
- [ ] Existing webhook creates task on board → thread is automatically created in matching alert channel
- [ ] Task and thread are linked bidirectionally (task.thread_id, thread.task_id)
- [ ] Duplicate webhook events (same source_ref) append to existing thread, no duplicate thread
- [ ] Channel hook failure does NOT prevent task creation (fail-safe)
- [ ] Direct channel webhook creates thread without creating a task
- [ ] Classifiers correctly route: GitHub Actions → build, deployments → deployment, tests → test
- [ ] Generic fallback catches unrecognised webhook formats
- [ ] Webhook events render as structured cards (see WP-6 for frontend)

---

## WP-5: Task ↔ Thread Bidirectional Sync

**Purpose**: Ensure board task comments and channel thread messages are the same data.
**Dependencies**: WP-1, WP-2
**Estimated effort**: 2–3 days

### 5.1 The Principle

When a Task has a `thread_id`:
- The task's "comments" ARE the thread's messages. There is no separate comments table.
- The existing task comment API should proxy to the thread message API.
- The existing task comment UI should read from the thread messages endpoint.

When a Task does NOT have a `thread_id` (legacy tasks):
- Behaviour is unchanged. Comments work exactly as they do today.

### 5.2 API Changes to Existing Task Endpoints

#### GET /api/tasks/{task_id}/comments (existing endpoint)

Modify to check if the task has a linked thread:

```python
def get_task_comments(task_id: str):
    task = get_task(task_id)

    if task.thread_id:
        # Proxy to thread messages
        return get_thread_messages(task.thread_id)
    else:
        # Legacy behaviour — return from existing comments table
        return get_legacy_task_comments(task_id)
```

#### POST /api/tasks/{task_id}/comments (existing endpoint)

```python
def create_task_comment(task_id: str, content: str):
    task = get_task(task_id)

    if task.thread_id:
        # Create a ThreadMessage instead
        return create_thread_message(
            thread_id=task.thread_id,
            sender_type="user",
            sender_id=current_user.id,
            content=content,
        )
        # This also triggers agent notification via WP-3
    else:
        # Legacy behaviour
        return create_legacy_task_comment(task_id, content)
```

### 5.3 Task Detail View Enhancement

The existing task detail page should show additional context when a thread is linked:

- **Channel badge**: Show which channel this task's thread belongs to, with a link to view it in the channel context
- **Thread status**: Show if the thread is resolved/pinned
- **Full conversation**: The comment list shows ALL thread messages, including webhook events and agent responses (not just user comments)

### 5.4 Thread Detail View Enhancement

The thread view in the channel should show when a task is linked:

- **Task badge**: Show the linked task's status (e.g., "In Progress", "Done"), title, and assignee
- **Task actions**: Quick actions to change task status directly from the thread view (without navigating to the board)
- **Unlink option**: Allow unlinking if the association was made in error

### 5.5 Creating Links

There are four ways a thread gets linked to a task:

1. **Webhook-driven (primary path)**: Existing board webhook creates a task → post-creation hook creates a thread and links them automatically (WP-4). This is the most common path for alert channels.
2. **Manual link from thread**: User clicks "Link to task" in the thread view, picks an existing task → sets thread.task_id (WP-2 endpoint)
3. **Manual link from task**: User clicks "Link to channel thread" in the task view, picks an existing thread → same operation
4. **Thread-first creation**: User creates a thread in a discussion channel and chooses "Also create a task" → creates task and links. This is the ONLY path where the channel system creates a task, and it's explicitly user-initiated (not automated).

### Acceptance Criteria
- [ ] Comments posted on a linked task appear in the channel thread
- [ ] Messages posted in a channel thread appear as comments on the linked task
- [ ] Agent responses in a thread appear in the task comment view
- [ ] Webhook events in a thread appear in the task comment view as system cards
- [ ] Legacy tasks (no thread_id) continue to work exactly as before
- [ ] Unlinking a task doesn't delete either the task or the thread
- [ ] Task status changes are visible in the thread view

---

## WP-6: Frontend — Channel Page & Components

**Purpose**: Build the channel messaging UI as a new sidebar item in Mission Control.
**Dependencies**: WP-2 (API must exist), WP-3 (agent responses should work for full testing)
**Estimated effort**: 5–7 days

### 6.1 New Route

```
frontend/src/app/channels/page.tsx          — Channel home (board group selector)
frontend/src/app/channels/[boardId]/page.tsx — Channels for a specific board
```

Add a new sidebar item in the main navigation (after the existing Boards item):
- Icon: MessageSquare or Hash (from lucide-react or your icon library)
- Label: "Channels"
- Route: /channels

### 6.2 Component Tree

```
frontend/src/components/channels/
├── ChannelsLayout.tsx         — Three-panel layout (sidebar + threads + messages)
├── BoardChannelSelector.tsx   — Top-level selector: which board's channels to view
├── ChannelSidebar.tsx         — Left panel: channel list grouped by type
│   ├── ChannelGroup.tsx       — Collapsible group ("Alert Channels", "Discussion Channels")
│   └── ChannelItem.tsx        — Single channel row (icon, name, unread badge)
├── ThreadList.tsx             — Middle panel: threads in the selected channel
│   ├── ThreadRow.tsx          — Single thread (topic, last message, timestamp, message count)
│   ├── ThreadFilters.tsx      — Toggle: Active / Resolved / Pinned
│   └── NewThreadButton.tsx    — Button to start a new conversation
├── MessageThread.tsx          — Right panel: messages in the selected thread
│   ├── MessageList.tsx        — Scrollable message list
│   ├── MessageBubble.tsx      — Individual message (different styles per sender_type)
│   ├── WebhookEventCard.tsx   — Structured card for webhook events (status badge, link, metadata)
│   ├── AgentResponseBubble.tsx — Agent message with avatar and agent name
│   ├── SystemMessage.tsx      — System notifications (thread created, task linked, etc.)
│   ├── ThreadHeader.tsx       — Topic, linked task badge, resolve/pin actions
│   ├── MessageComposer.tsx    — Text input with @mention autocomplete and send button
│   └── MentionAutocomplete.tsx — Dropdown of available agents when typing @
└── ChannelSettings.tsx        — Channel configuration (webhook URL, subscriptions, etc.)
```

### 6.3 Layout

Use a three-panel layout similar to Zulip's or Slack's:

```
┌──────────┬────────────────────┬──────────────────────────────┐
│ Channels │ Threads            │ Messages                     │
│          │                    │                              │
│ ALERTS   │ api-service/main   │ [webhook] Build #1234 FAILED │
│ ● Build  │ — Build #1234      │                              │
│   Deploy │                    │ [user] @devops what broke?   │
│   Tests  │ auth-service/dev   │                              │
│   Prod   │ — Build #891       │ [agent] The test in /api/... │
│          │                    │                              │
│ DISCUSS  │ frontend/main      │ [user] Can you fix it?       │
│   Dev    │ — Build #567       │                              │
│ ● DevOps │                    │ [agent] Created PR #89       │
│   Test   │                    │                              │
│   Arch   │                    │ ─── Compose ──────────────── │
│   General│                    │ │ Type a message... [@]  ▶ │ │
│          │                    │ ──────────────────────────── │
└──────────┴────────────────────┴──────────────────────────────┘

● = has unread messages
```

On mobile (responsive), collapse to: Channel list → Thread list → Message thread (back-navigable).

### 6.4 Real-Time Updates

Hook into Mission Control's existing WebSocket/SSE connection for live updates:

```typescript
// frontend/src/hooks/useChannelMessages.ts

// Subscribe to new messages for the current thread
useEffect(() => {
  const handler = (event: WebSocketEvent) => {
    if (event.type === "channel_message" && event.thread_id === selectedThreadId) {
      setMessages(prev => [...prev, event.message]);
      scrollToBottom();
    }
    if (event.type === "channel_message" && event.channel_id === selectedChannelId) {
      // Update thread list (new message preview, reorder by last_message_at)
      updateThreadPreview(event.thread_id, event.message);
    }
    if (event.type === "channel_unread_update") {
      // Update unread badges in sidebar
      updateUnreadCount(event.channel_id, event.unread_count);
    }
  };
  websocket.addEventListener("message", handler);
  return () => websocket.removeEventListener("message", handler);
}, [selectedThreadId, selectedChannelId]);
```

### 6.5 Webhook Event Card Component

Webhook events should render as structured cards, not plain text:

```tsx
// frontend/src/components/channels/WebhookEventCard.tsx

// Props from ThreadMessage where content_type === "webhook_event"
// metadata contains: source, event_type, severity, url, and parsed fields

// Render:
// ┌──────────────────────────────────────────┐
// │ ❌ Build FAILED                          │
// │                                          │
// │ Repository: api-service                  │
// │ Branch:     main                         │
// │ Commit:     a1b2c3d "Fix auth flow"      │
// │ Duration:   3m 42s                       │
// │                                          │
// │ [View on GitHub →]                       │
// └──────────────────────────────────────────┘
//
// Severity colours:
// - info:     blue/grey border
// - warning:  yellow/amber border
// - error:    red border
// - critical: red border + red background tint
```

### 6.6 @Mention Autocomplete

When the user types `@` in the MessageComposer:

1. Fetch agents subscribed to the current channel
2. Show a dropdown with agent name, avatar, and role
3. On selection, insert `@agent-name` into the message
4. Submitted message includes the @mention which triggers agent routing in WP-3

### 6.7 Linked Task Badge

When a thread has a linked task, show a compact badge in the ThreadHeader:

```tsx
// ┌─────────────────────────────────────────────┐
// │ 🔗 Task: BOARD-123 "Fix authentication bug" │
// │    Status: In Progress  │  Assignee: @dev   │
// │    [View Task →]  [Unlink]                   │
// └─────────────────────────────────────────────┘
```

### Acceptance Criteria
- [ ] Channel sidebar shows all channels for the selected board with correct unread counts
- [ ] Thread list shows threads sorted by last activity, with pinned threads first
- [ ] Message thread displays all message types correctly (user, agent, webhook, system)
- [ ] Webhook events render as structured cards with severity styling
- [ ] @mention autocomplete works and triggers agent notification
- [ ] Real-time updates work (new messages appear without refresh)
- [ ] Linked task badge is shown and links to the board task view
- [ ] Responsive layout works on mobile
- [ ] Follows existing Mission Control design system (Tailwind classes, component patterns)

---

## WP-7: Board Task View Integration

**Purpose**: Update the existing board task UI to show channel thread context.
**Dependencies**: WP-5, WP-6
**Estimated effort**: 2–3 days

### 7.1 Task Detail Panel Changes

When viewing a task that has a linked thread (`thread_id is not null`):

1. **Channel context banner**: At the top of the task detail, show:
   ```
   📌 This task is linked to: #build-alerts > "api-service/main — Build #1234"
   [Open in Channels →]
   ```

2. **Comments section**: Replace the existing comments list with the ThreadMessage list (reading from `/api/threads/{thread_id}/messages`). This shows the full conversation including webhook events and agent responses, not just user comments.

3. **Comment composer**: The existing "Add comment" input should post to `/api/threads/{thread_id}/messages` instead of the legacy comments endpoint.

4. **Visual distinction**: Webhook event messages in the task comment view should render as the same WebhookEventCard component from WP-6. Agent responses should show the agent's name and avatar.

### 7.2 Task List Indicators

In the board's task list (Kanban or list view), tasks with linked threads should show a small icon indicating:
- Which channel they're linked to
- How many messages are in the thread
- Whether there are unread messages in the thread

### 7.3 Task Creation from Channels (User-Initiated Only)

For discussion channels (not alert channels), a user may want to escalate a conversation into a tracked task. This is an explicit user action, never automatic:

- User clicks "Create task from thread" in the thread header
- A task is created on the board with:
  - Title: the thread topic
  - Description: the first message content
  - Source: "Channel: #{channel_name}"
  - Thread link: bidirectional
- This is the ONLY scenario where the channel system creates a task
- For alert channels, tasks are always created by the existing webhook pipeline, and threads are linked automatically by the WP-4 hook

### 7.4 Backward Compatibility

Tasks without a `thread_id` (all existing tasks) must continue to work exactly as they do today. The legacy comments system is untouched for these tasks. Only tasks with a `thread_id` use the new ThreadMessage system.

### Acceptance Criteria
- [ ] Task detail shows channel context banner when linked to a thread
- [ ] Task comments show full thread messages (including webhooks, agent responses)
- [ ] Adding a comment on a linked task appears in the channel thread
- [ ] Legacy tasks (no thread) are completely unaffected
- [ ] Task list shows thread indicator icons
- [ ] "Create task from thread" works in discussion channels

---

## WP-8: Testing, Documentation & Configuration

**Purpose**: Ensure reliability, document the feature, and provide configuration options.
**Dependencies**: All other WPs
**Estimated effort**: 3–4 days

### 8.1 Backend Tests

```
backend/tests/
├── test_channel_api.py         — CRUD operations on channels
├── test_thread_api.py          — Thread creation, deduplication, linking
├── test_message_api.py         — Message CRUD, pagination, unread tracking
├── test_board_lifecycle.py     — Board create → channels created; board delete → channels archived
├── test_agent_lifecycle.py     — Agent added/removed/lead changed → subscriptions updated
├── test_webhook_hook.py        — Post-creation hook: task created by webhook → thread created in channel
├── test_webhook_classifiers.py — Each classifier correctly categorises payloads
├── test_webhook_dedup.py       — Duplicate webhook handling (same source_ref → same thread)
├── test_direct_webhook.py      — Direct channel webhook (thread only, no task)
├── test_agent_routing.py       — Agent notification logic (lead, mentions, subscriptions)
├── test_task_thread_sync.py    — Bidirectional task ↔ thread operations
└── test_migration.py           — Migration on fresh DB and DB with existing data
```

Key test scenarios:
- New board created → all 9 default channels created with correct types and settings
- Board deleted → all channels archived (soft delete) with threads and messages preserved
- Board hard-deleted → all channel data cascade-deleted
- Board lead agent changed → old lead unsubscribed, new lead subscribed to all channels
- Agent added to board → subscribed to discussion channels with "mentions" notify
- Agent removed from board → all channel subscriptions removed
- Existing webhook creates task → post-creation hook creates thread in matching alert channel → task and thread linked
- Comment on linked task → appears in channel thread
- Message in channel thread → appears as comment on linked task
- User posts in discussion channel → board lead agent responds → response in both views
- Duplicate webhook (same source_ref) → appends to existing thread, no duplicate thread
- Post-creation hook fails → task is still created successfully (fail-safe)
- Direct channel webhook → creates thread without task
- Agent @mentioned in channel → only that agent is notified (not all agents)
- Channel archived → no new messages can be posted
- Unread count is accurate after reading, after new messages, after mark-all-read

### 8.2 Frontend Tests

```
frontend/src/__tests__/channels/
├── ChannelSidebar.test.tsx     — Renders channels, unread badges, selection
├── ThreadList.test.tsx         — Thread rendering, filtering, sorting
├── MessageThread.test.tsx      — Message display, different sender types
├── WebhookEventCard.test.tsx   — Card rendering for each webhook type
├── MessageComposer.test.tsx    — Input, @mention autocomplete, send
└── TaskThreadSync.test.tsx     — Linked task display in thread, and thread display in task
```

### 8.3 Documentation

Create `docs/channels.md` covering:

1. **User guide**: How to use channels, post messages, view alerts, link tasks
2. **Webhook setup guide**: How to configure external services (GitHub Actions, GitLab CI, ArgoCD) to send webhooks to Mission Control channels. Include example payloads and webhook URLs.
3. **Agent configuration**: How to set up agent subscriptions to channels, and how the board lead vs. other agents interact with channels
4. **Channel management**: How to create custom channels, archive channels, manage webhook secrets
5. **Architecture overview**: The unified thread model, how task ↔ thread sync works

### 8.4 Configuration Options

Add these to the environment/config:

```env
# Channels feature toggle (for gradual rollout)
CHANNELS_ENABLED=true

# Default channels to create for new boards (JSON array, or "standard" for the defaults)
DEFAULT_CHANNELS=standard

# Maximum messages per thread before auto-summarisation kicks in
CHANNEL_THREAD_MAX_MESSAGES_CONTEXT=20

# Message retention (0 = forever)
CHANNEL_MESSAGE_RETENTION_DAYS=0

# Whether the post-creation hook runs on webhook-created tasks (creates linked threads)
CHANNEL_WEBHOOK_HOOK_ENABLED=true
```

### 8.5 Migration Runbook

Document the step-by-step process for deploying this feature to an existing Mission Control instance:

1. Pull latest code
2. Run database migration (`make migrate` or equivalent)
3. Verify default channels created for existing boards
4. Configure webhook URLs in external services (GitHub, etc.)
5. Test a webhook → verify it appears in the alert channel
6. Test posting in a discussion channel → verify agent responds

### Acceptance Criteria
- [ ] Backend test coverage ≥ 80% for new code
- [ ] Frontend component tests pass
- [ ] End-to-end test: webhook → channel → agent response → visible in task view
- [ ] Documentation complete and accurate
- [ ] Configuration options work as documented
- [ ] Feature toggle can disable channels entirely without breaking existing functionality
- [ ] Migration runbook tested on a fresh instance and an existing instance

---

## Dependency Graph & Parallelisation

```
WP-1 (Schema)
 │
 ├──→ WP-2 (API) ──→ WP-6 (Frontend)
 │     │                    │
 │     ├──→ WP-3 (Agent Routing) ──→ WP-6 (Frontend, real-time)
 │     │
 │     ├──→ WP-4 (Webhooks) ──→ WP-6 (Webhook cards)
 │     │
 │     └──→ WP-5 (Task Sync) ──→ WP-7 (Board Task UI)
 │
 └──→ WP-8 (Testing & Docs) — runs continuously alongside all WPs
```

**Parallel tracks after WP-1 is done:**
- **Track A (Backend)**: WP-2 → WP-3 → WP-4 → WP-5
- **Track B (Frontend)**: Can start WP-6 with mocked API once WP-2's interface is defined
- **Track C (Integration)**: WP-7 starts once WP-5 and WP-6 are done
- **Track D (Quality)**: WP-8 runs continuously

**Critical path**: WP-1 → WP-2 → WP-3 → WP-6 (with real-time) → WP-7

---

## Summary of File Locations

### Backend (new files)
```
backend/src/models/channel.py
backend/src/models/thread.py
backend/src/models/thread_message.py
backend/src/models/channel_subscription.py
backend/src/models/user_channel_state.py
backend/src/api/channels.py                  (channel endpoints)
backend/src/api/threads.py                   (thread endpoints)
backend/src/api/messages.py                  (message endpoints)
backend/src/services/channel_lifecycle.py     (board lifecycle hooks: create/delete/agent changes)
backend/src/services/channel_thread_hook.py   (post-task-creation hook for webhook → thread)
backend/src/services/agent_routing.py         (channel-aware agent dispatch)
backend/src/services/thread_service.py        (thread creation, dedup, linking)
backend/src/services/unread_service.py        (unread count management)
backend/src/webhooks/classifier.py            (classifier interface + registry)
backend/src/webhooks/github_actions.py        (GitHub Actions classifier)
backend/src/webhooks/github_pr.py             (GitHub PR classifier)
backend/src/webhooks/deployment.py            (generic deployment classifier)
backend/src/webhooks/test_results.py          (generic test classifier)
backend/src/webhooks/generic.py               (fallback classifier)
backend/src/migrations/xxx_add_channels.py
```

### Backend (modified files)
```
backend/src/models/task.py               (add thread_id column)
backend/src/api/tasks.py                 (proxy comments to thread when linked)
backend/src/api/boards.py                (add lifecycle hook calls: on_board_created, on_board_deleted)
backend/src/api/agents.py                (add lifecycle hook calls: on_agent_added/removed, on_lead_changed)
backend/src/services/gateway.py          (extend message envelope for channels)
backend/src/api/webhooks.py              (add post-creation hook call for channel thread)
```

### Frontend (new files)
```
frontend/src/app/channels/page.tsx
frontend/src/app/channels/[boardId]/page.tsx
frontend/src/components/channels/ChannelsLayout.tsx
frontend/src/components/channels/BoardChannelSelector.tsx
frontend/src/components/channels/ChannelSidebar.tsx
frontend/src/components/channels/ChannelGroup.tsx
frontend/src/components/channels/ChannelItem.tsx
frontend/src/components/channels/ThreadList.tsx
frontend/src/components/channels/ThreadRow.tsx
frontend/src/components/channels/ThreadFilters.tsx
frontend/src/components/channels/NewThreadButton.tsx
frontend/src/components/channels/MessageThread.tsx
frontend/src/components/channels/MessageList.tsx
frontend/src/components/channels/MessageBubble.tsx
frontend/src/components/channels/WebhookEventCard.tsx
frontend/src/components/channels/AgentResponseBubble.tsx
frontend/src/components/channels/SystemMessage.tsx
frontend/src/components/channels/ThreadHeader.tsx
frontend/src/components/channels/MessageComposer.tsx
frontend/src/components/channels/MentionAutocomplete.tsx
frontend/src/components/channels/ChannelSettings.tsx
frontend/src/hooks/useChannelMessages.ts
frontend/src/hooks/useUnreadCounts.ts
frontend/src/hooks/useThreadSubscription.ts
```

### Frontend (modified files)
```
frontend/src/components/navigation/Sidebar.tsx   (add Channels nav item)
frontend/src/components/tasks/TaskDetail.tsx      (add thread context banner + proxy comments)
frontend/src/components/tasks/TaskList.tsx         (add thread indicator icons)
frontend/src/api/generated/                        (regenerate from updated OpenAPI spec)
```

### Documentation (new files)
```
docs/channels.md
docs/webhook-setup.md
docs/channels-architecture.md
```