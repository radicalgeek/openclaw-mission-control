# Support Channel: Bug Fix & Thread Privacy Plan

## Status

| Item | Status |
|------|--------|
| Bug fix: composer grayed out after send | ✅ Fixed in this session |
| Thread privacy: investigation | ✅ Done |
| Thread privacy: implementation | 🔲 Planned below |

---

## Bug: Message stays grayed out, can't post another

### Root Cause

`handleSend` in `MessageThread.tsx` was clearing `composerText` **after** awaiting the API
response, gated behind `if (result.status === 201)`. During the round-trip:

1. `isSending = true` → `disabled={isSending}` makes the `<textarea>` show at `opacity-50`
   (grayed out) and the Send button disabled.
2. Network completes. On success (`201`) `setComposerText("")` fires, then
   `setIsSending(false)` fires in `finally`.
3. On any other outcome (non-201 success, non-ok response caught by ApiError) — text was
   NOT cleared. `isSending` did reset, but the user observed the greyed-out textarea
   during step 2 and concluded it was stuck.

A secondary factor: after a successful send, the send button becomes `disabled={!composerText.trim()}` (because the text is empty), which also appears greyed-out. Users saw the button as "still stuck" rather than "correctly disabled because empty".

### Fix Applied

`frontend/src/components/channels/MessageThread.tsx` — `handleSend`:

- `composerText` is now cleared **optimistically before** the `await`, so the textarea is
  never locked with the user's text visible inside it.
- On failure (non-201 or caught error) the trimmed text is **restored** so the user can
  retry without re-typing.
- `composerRef.current?.focus()` is called in `finally` to return keyboard focus to the
  composer automatically after send.

---

## Feature: Support Channel Thread Privacy

### Current Behaviour (problem)

All board leads subscribed to the `#support` channel can see **all threads** from all
boards. An agent escalating a sensitive infrastructure issue or deployment secret can be
read by every other board lead. Similarly, any subscribed agent can reply to any thread,
creating noise for the platform team.

### Target Behaviour

| Actor | Can create thread | Sees threads | Can reply |
|-------|-------------------|--------------|-----------|
| Human operator | ✅ | All | All |
| Platform board lead (agent) | ✅ | All | All |
| Non-platform board lead (agent) | ✅ | Own board's only | Own board's threads only |
| Non-platform worker agent | ❌ (shouldn't be subscribed) | Own board's only | Own board's threads only |

"Own board's threads" = threads where `Thread.creator_board_id` matches the caller's board.

### Architecture

#### Data model change

Add two nullable columns to the `threads` table:

```
threads.creator_agent_id  UUID  FK → agents.id  (nullable)
threads.creator_board_id  UUID  FK → boards.id  (nullable)
```

- Set on `POST /channels/{channel_id}/threads` when the actor is an agent.
- NULL for webhook-created threads and threads created by human operators (humans see
  all threads anyway, so filtering is never needed).
- Existing rows remain NULL — treated as "visible to all" during migration period; the
  platform lead sees them regardless.

#### Identifying the Support channel

The support channel has `slug = "support"` and belongs to the board where
`board.is_platform = True`. This is the only channel in the system with these
combined attributes. Access-control logic gates on:

```python
channel.slug == "support" and channel_board.is_platform
```

For all other channels, current behaviour is unchanged.

#### Identifying the platform board lead

An agent is the platform lead if:
- `agent.is_board_lead is True`
- `agent.board_id == (the platform board id)`

Query: join Board where `is_platform = True`, compare agent's `board_id`.

---

### Implementation Plan

#### WP-1 — Database migration

**File**: `backend/migrations/versions/<timestamp>_add_thread_creator_fields.py`

```python
op.add_column("threads", sa.Column("creator_agent_id", sa.UUID(), nullable=True))
op.add_column("threads", sa.Column("creator_board_id", sa.UUID(), nullable=True))
op.create_index("ix_threads_creator_board_id", "threads", ["creator_board_id"])
op.create_foreign_key(None, "threads", "agents", ["creator_agent_id"], ["id"],
    ondelete="SET NULL")
op.create_foreign_key(None, "threads", "boards", ["creator_board_id"], ["id"],
    ondelete="SET NULL")
```

Downgrade removes the columns and indexes.

---

#### WP-2 — Thread model

**File**: `backend/app/models/thread.py`

Add to `Thread`:

```python
creator_agent_id: UUID | None = Field(default=None, foreign_key="agents.id",
    index=True, ondelete="SET NULL")
creator_board_id: UUID | None = Field(default=None, foreign_key="boards.id",
    index=True, ondelete="SET NULL")
```

---

#### WP-3 — Schema update

**File**: `backend/app/schemas/threads.py`

Add to `ThreadRead`:

```python
creator_board_id: UUID | None = None
```

Not exposing `creator_agent_id` publicly (not needed by frontend).

Update `_to_thread_read()` in `threads.py` to populate `creator_board_id`.

---

#### WP-4 — Access control helper

**File**: `backend/app/services/support_channel_acl.py` (new)

```python
"""Access-control helpers for the platform #support channel."""

async def is_support_channel(session, channel_id) -> bool:
    """Returns True if this channel is the platform support channel."""

async def get_platform_board_id(session, gateway_id=None) -> UUID | None:
    """Returns the platform board's ID, if one exists."""

async def support_channel_can_view_thread(
    session, actor: ActorContext, thread: Thread, support_channel: Channel
) -> bool:
    """
    Returns True if the actor can see this thread.
    Rules:
    - Human operators: always True
    - Platform board lead: always True
    - Other agents: only if thread.creator_board_id == actor's board_id
                    (or creator_board_id is None for legacy threads)
    """

async def support_channel_can_reply(
    session, actor: ActorContext, thread: Thread, support_channel: Channel
) -> bool:
    """Same rules as view — can't reply what you can't see."""
```

---

#### WP-5 — Thread creation: capture creator

**File**: `backend/app/api/threads.py` — `create_channel_thread`

After determining the actor:

```python
creator_agent_id = None
creator_board_id = None
if is_support and isinstance(actor, ActorContext) and actor.actor_type == "agent":
    creator_agent_id = actor.agent.id
    creator_board_id = actor.agent.board_id
```

Set both on the new `Thread` object before flush.

---

#### WP-6 — Thread list: visibility filter

**File**: `backend/app/api/threads.py` — `list_channel_threads`

After fetching threads:

```python
if await is_support_channel(session, channel_id):
    threads = [
        t for t in threads
        if await support_channel_can_view_thread(session, actor, t, channel)
    ]
```

Where `actor` is injected via `ACTOR_DEP` (change the dep on this route from
`ORG_MEMBER_DEP` to `ACTOR_DEP` to allow agents to call it).

**Note**: `list_channel_threads` currently uses `ORG_MEMBER_DEP` which only admits
humans. The route already works for agents via subscriptions in the heartbeat template
(agents call it with `X-Agent-Token`). Change to `ACTOR_DEP` to unify.

---

#### WP-7 — Thread get: visibility check

**File**: `backend/app/api/threads.py` — `get_thread`

```python
if await is_support_channel(session, thread.channel_id):
    if not await support_channel_can_view_thread(session, actor, thread, channel):
        raise HTTPException(status_code=403, detail="Thread not visible.")
```

Change dep to `ACTOR_DEP`.

---

#### WP-8 — Message posting: reply permission check

**File**: `backend/app/api/thread_messages.py` — `create_thread_message`

```python
if await is_support_channel(session, channel.id):
    if not await support_channel_can_reply(session, actor, thread, channel):
        raise HTTPException(status_code=403,
            detail="You can only reply to your own support threads.")
```

---

#### WP-9 — Messages list: read permission

**File**: `backend/app/api/thread_messages.py` — `list_thread_messages`

Same pattern as WP-7 — gate on `support_channel_can_view_thread`.

---

#### WP-10 — Frontend

**No functional changes required.** The API will return only the threads the caller can
see. The thread list UI will just show fewer items.

Optional UX improvement (separate ticket): show a banner in the Support channel for
non-platform board leads explaining that they only see their own escalation threads.

---

#### WP-11 — Agent template update

**File**: `backend/templates/BOARD_HEARTBEAT.md.j2`

The platform lead triage section (already updated in `4951ae4`) correctly uses the
channel slug `support` to find the channel. No changes needed.

The non-platform lead escalation section (Platform Support Escalation) also requires no
changes — agents create threads and can only see responses to their own.

---

#### WP-12 — Tests

**File**: `backend/tests/channels/test_support_channel_acl.py` (new)

| Test | Assertion |
|------|-----------|
| Platform lead sees all threads | Returns N threads from N boards |
| Human operator sees all threads | Returns N threads (using user auth) |
| Board-A lead only sees board-A threads | Threads from board-B are absent |
| Board-A lead can reply to own thread | 201 |
| Board-A lead cannot reply to board-B thread | 403 |
| Board-A lead cannot GET board-B thread | 403 |
| Board-A lead cannot list board-B messages | 403 |
| Creator fields set on thread create | `creator_board_id` matches actor board |
| Legacy NULL threads visible to all | NULL `creator_board_id` → visible |

---

### Sequencing / Dependencies

```
WP-1 (migration)
  └── WP-2 (model)
        └── WP-3 (schema)
              ├── WP-4 (ACL helpers)  ← build and unit-test in isolation
              │     ├── WP-5 (create: capture creator)
              │     ├── WP-6 (list: visibility filter)
              │     ├── WP-7 (get: visibility check)
              │     └── WP-8 + WP-9 (messages: reply/read permission)
              └── WP-12 (tests, written alongside WP-5−9)
```

WP-10 (frontend) and WP-11 (templates) can land independently.

---

### Not in scope

- Audit log for support thread reads (could add later via activity_events).
- Direct messages between board leads and the platform team (separate feature).
- Notifications when the platform team replies (future: WebSocket / polling improvement).
- UI banner explaining the scoped visibility (follow-up UX ticket).
