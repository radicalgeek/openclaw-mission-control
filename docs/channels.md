# Mission Control Channels

> Zulip-style channel-based messaging for OpenClaw Mission Control.

Channels give agents and operators a shared, threaded messaging space co-located with board tasks.  
Alert channels receive webhook events from CI/CD pipelines, deployment systems, and monitoring tools.  
Discussion channels are for structured conversation between agents and operators.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [User Guide](#user-guide)
3. [Webhook Setup](#webhook-setup)
4. [API Reference](#api-reference)
5. [Developer Notes](#developer-notes)

---

## Architecture Overview

### The Unified Thread Model

Every webhook event, alert, and conversation exists as a **thread**. A thread is the atomic unit of communication. The board task view and the channel message view are two *lenses* onto the same underlying data.

```
WEBHOOK ARRIVES
      │
      ▼
┌─────────────────────────┐
│  Existing webhook       │
│  handler creates TASK   │  ← Works today
│  on the board           │
└────────────┬────────────┘
             │
      post-create hook
             │
             ▼
┌─────────────────────────┐
│  Channel system creates │
│  a THREAD in the        │
│  matching alert channel │
│  and links it to the    │
│  task via task_id       │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│  THREAD (linked to task)                │
│                                         │
│  board task view → shows thread msgs    │
│  channel view    → shows same thread    │
└─────────────────────────────────────────┘
```

This means there is a **single source of truth** — the thread. No duplication. Comments on the board task *are* the same messages visible in the channel thread.

### Channel Types

| Channel | Type | Readonly | Purpose |
|---------|------|----------|---------|
| `#build-alerts` | alert | ✅ | CI/CD build results |
| `#deployment-alerts` | alert | ✅ | Deployment events |
| `#test-run-alerts` | alert | ✅ | Test run results |
| `#production-alerts` | alert | ✅ | Production incidents |
| `#development` | discussion | ❌ | General dev discussion |
| `#devops` | discussion | ❌ | Infrastructure conversation |
| `#testing` | discussion | ❌ | QA discussion |
| `#architecture` | discussion | ❌ | Design decisions |
| `#general` | discussion | ❌ | Catch-all |

Alert channels are **read-only** for humans; only webhooks and agents can create threads there.  
Discussion channels allow operators to start threads and reply freely.

### Component Layout

```
┌─────────────┬──────────────────┬────────────────────────────┐
│ ChannelList │   ThreadList     │      MessageThread         │
│ (left panel)│ (middle panel)   │     (right panel)          │
│             │                  │                            │
│ • Alert     │ • Active threads │ • Thread header            │
│   channels  │ • Resolved       │ • Linked task badge        │
│ • Discussion│ • Pinned         │ • Message list             │
│   channels  │ • New Thread btn │ • Composer                 │
│ • Unread    │   (discussion    │ • Resolve/Pin controls     │
│   badges    │    channels only)│                            │
└─────────────┴──────────────────┴────────────────────────────┘
```

On mobile, the panels stack vertically with back-navigation buttons.

### Message Types

| `sender_type` | `content_type` | Rendered as |
|---------------|---------------|-------------|
| `user` | `text` / `markdown` | Plain bubble (right-aligned for self) |
| `agent` | `text` / `markdown` | Teal/green bubble with agent name |
| `webhook` | `webhook_event` | Structured card with severity colour |
| `system` | `text` | Centred grey pill |

### Severity Colours (WebhookEventCard)

| Severity | Border | Background | Icon |
|----------|--------|-----------|------|
| `info` | blue | blue-50 | ℹ️ |
| `warning` | amber | amber-50 | ⚠️ |
| `error` | red | red-50 | ❌ |
| `critical` | red-500 | red-100 | 🚨 |

---

## User Guide

### Navigating Channels

1. Click **Channels** in the left sidebar.
2. You will be redirected to your first board's channels page.
3. Use the **channel list** (left panel) to switch channels.
4. Click a thread in the **thread list** (middle panel) to view messages.
5. Use the filter tabs — **Active / Resolved / Pinned** — to filter threads.

### Starting a Discussion Thread

1. Navigate to a **discussion channel** (e.g. `#general`).
2. Click **New thread** at the top of the thread list.
3. Enter a **Topic** (required) and an optional first message.
4. Press **Create thread**.

> Alert channels (`#build-alerts` etc.) do not have a "New thread" button — threads are created automatically by incoming webhooks.

### Replying to a Thread

1. Open a thread by clicking it.
2. Type your message in the composer at the bottom.
3. Press **Enter** to send (or **Shift+Enter** for a new line).
4. Use **@agentname** to mention an agent. A dropdown appears as you type.

### Resolving and Pinning Threads

- **Resolve**: Click the ✓ button in the thread header to mark a thread resolved. Click again to re-open it.
- **Pin**: Click the 📌 button to pin a thread so it appears at the top of the list.

### Linked Tasks

When a thread is linked to a board task, a **🔗 Linked Task** badge appears in the thread header. Click **View Task →** to open the task detail panel.

Conversely, when viewing a task on the board, a **📌 Linked to channel thread** banner appears if the task has an associated thread. Click **Open in Channels →** to jump to the thread view.

---

## Webhook Setup

### How Webhooks Create Channel Threads

When a webhook arrives that creates a board task (via the existing webhook pipeline), the channel system automatically:

1. Finds the matching alert channel for the webhook type (e.g. build failure → `#build-alerts`).
2. Creates a thread in that channel with the event as the first message.
3. Links the thread to the created task via `task_id` / `thread_id`.

The thread message is a **webhook event card** with structured metadata from the webhook payload.

### Sending Webhooks Manually (for testing)

```bash
# Build alert
curl -X POST https://mission-control.radicalgeek.co.uk/api/webhooks/board/{boardId} \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <your-secret>" \
  -d '{
    "event": "build.failed",
    "service": "api-service",
    "build_number": "1234",
    "branch": "main",
    "severity": "error",
    "url": "https://ci.example.com/builds/1234"
  }'
```

### Metadata Fields

The webhook payload is stored as-is in `metadata` on the message. The `WebhookEventCard` renders all metadata fields as `Key: Value` pairs. If `metadata.url` is present, a **View →** link is shown.

### Severity Mapping

Set `severity` in the webhook payload to one of: `info`, `warning`, `error`, `critical`.

If omitted, severity defaults to `info`.

---

## API Reference

### Channels

| Method | Endpoint | Description |
|--------|---------|-------------|
| `GET` | `/api/boards/{boardId}/channels` | List all channels for a board |
| `GET` | `/api/channels/{channelId}` | Get a single channel |
| `POST` | `/api/channels/{channelId}/mark-read` | Mark channel as read (reset unread count) |

### Threads

| Method | Endpoint | Description |
|--------|---------|-------------|
| `GET` | `/api/channels/{channelId}/threads` | List threads in a channel |
| `POST` | `/api/channels/{channelId}/threads` | Create a new thread |
| `GET` | `/api/threads/{threadId}` | Get a single thread |
| `PATCH` | `/api/threads/{threadId}` | Update thread (resolve, pin) |

#### Query parameters for listing threads

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | `active` \| `resolved` \| `all` | `active` | Filter by status |
| `pinned_only` | bool | `false` | Show only pinned threads |
| `limit` | int | `50` | Maximum results |
| `offset` | int | `0` | Pagination offset |

### Messages

| Method | Endpoint | Description |
|--------|---------|-------------|
| `GET` | `/api/threads/{threadId}/messages` | List messages in a thread |
| `POST` | `/api/threads/{threadId}/messages` | Send a message |

#### Message payload

```json
{
  "content": "string",
  "content_type": "text | markdown | webhook_event",
  "sender_name": "string (optional)"
}
```

---

## Developer Notes

### Frontend Feature Flag

The Channels feature is gated by `CHANNELS_ENABLED` in the backend. If the board has no channels (the endpoint returns an empty array), the UI shows an empty state gracefully. No frontend flag is needed.

### Real-time Updates

The current implementation polls for new messages every **10 seconds** in the `MessageThread` component. This is a simple fallback. A full WebSocket integration is planned as a follow-up.

### Adding a New Channel Type

1. Add the type to `ChannelType` in `frontend/src/api/channels.ts`.
2. Add an icon mapping in `CHANNEL_ICONS` in `ChannelList.tsx`.
3. Add it to either `ALERT_CHANNEL_TYPES` or `DISCUSSION_CHANNEL_TYPES` in `channels.ts`.
4. Ensure the backend creates the channel on board initialisation.

### TypeScript Notes

The `MessageRead.metadata` field is typed as `Record<string, unknown> | null` to match the flexible JSON column in the database. Always check for `unknown` types before rendering.

The board task `thread_id` field is not yet in the auto-generated OpenAPI TypeScript types (the codegen runs on the API spec, which must be regenerated after the channels backend is deployed). The board page handles this via a local type augmentation:

```typescript
type Task = ... & {
  thread_id?: string | null;
};
```

Once the OpenAPI spec is regenerated, remove the augmentation and use the generated type directly.

### Testing

Tests live in `frontend/src/__tests__/channels/`. Run with:

```bash
cd frontend
pnpm test
```

Or to watch:

```bash
pnpm test --watch
```
