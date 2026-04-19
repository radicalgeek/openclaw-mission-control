# Standalone Agents — Implementation Record

**Plan reference:** `STANDALONE_AGENTS_PLAN.md`  
**Status:** All 6 phases complete  
**Date completed:** April 2026

---

## Overview

Standalone agents are a new agent type that are not bound to a board. They connect to a gateway for authentication and configuration, can be triggered by inbound HTTP webhooks, and can access boards they are explicitly granted permission to. This extends the existing agent model which previously required every agent to belong to a board.

---

## Phase 1 — Database Schema

**Migration:** `d1f2a3b4c5e6_add_standalone_agent_tables.py`

### Changes to `agents` table

| Column | Type | Notes |
|---|---|---|
| `agent_type` | `VARCHAR(32)` NOT NULL | `board_worker`, `board_lead`, `gateway_main`, `standalone`. Backfilled from existing `board_id` / `is_board_lead` values on migration. Indexed. |
| `installed_skills` | `JSON` nullable | Per-agent skill allowlist. `null` means inherit gateway defaults. |

### New table: `agent_webhooks`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `agent_id` | UUID FK → `agents.id` CASCADE | |
| `organization_id` | UUID FK → `organizations.id` CASCADE | |
| `description` | TEXT | |
| `enabled` | BOOLEAN | default `true` |
| `secret` | TEXT nullable | HMAC signing secret, stored in plaintext (consider encrypting at rest) |
| `signature_header` | TEXT nullable | Header name for HMAC signature, e.g. `X-Hub-Signature-256` |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

### New table: `agent_webhook_payloads`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `agent_id` | UUID FK → `agents.id` CASCADE | |
| `webhook_id` | UUID FK → `agent_webhooks.id` CASCADE | |
| `payload` | JSON | Raw request body |
| `headers` | JSON | Sanitised request headers |
| `source_ip` | TEXT nullable | |
| `content_type` | TEXT nullable | |
| `received_at` | TIMESTAMPTZ indexed | |

### New table: `agent_board_access`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `agent_id` | UUID FK → `agents.id` CASCADE | |
| `board_id` | UUID FK → `boards.id` CASCADE | |
| `access_level` | `VARCHAR(16)` | `read` or `write` |
| `created_at` | TIMESTAMPTZ | |

Unique constraint on `(agent_id, board_id)`.

---

## Phase 2 — Backend API Routes

### New API modules

#### `backend/app/api/agent_webhooks.py`
Router prefix: `/api/v1/agents/{agent_id}/webhooks`

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | List all webhooks for an agent |
| `POST` | `/` | Create a webhook; returns the generated `endpoint_url` |
| `PATCH` | `/{webhook_id}` | Update description, enabled state, secret, or signature header |
| `DELETE` | `/{webhook_id}` | Delete webhook and cascade payloads |
| `GET` | `/{webhook_id}/payloads` | Recent inbound payloads (default limit 20) |
| `POST` | `/ingest/{endpoint_path}` | Public unauthenticated ingest endpoint; verifies HMAC if secret is set |

#### `backend/app/api/agent_board_access.py`
Router prefix: `/api/v1/agents/{agent_id}/board-access`

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | List all board access grants for an agent |
| `POST` | `/` | Grant access to a board at `read` or `write` level |
| `DELETE` | `/{grant_id}` | Revoke a board access grant |

#### `backend/app/api/agent_skills.py`
Router prefix: `/api/v1/agents/{agent_id}/skills`

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Get the agent's skill allowlist (`null` = use gateway defaults) |
| `PATCH` | `/` | Update the allowlist; set `installed_skills: null` to revert to gateway defaults |

### Changes to `backend/app/api/agents.py`

- `POST /api/v1/agents` accepts optional `agent_type` and `gateway_id`. When `agent_type == "standalone"`, `board_id` is not required and the agent is created without a board relationship.
- `GET /api/v1/agents/{agent_id}` response now includes `agent_type` and `installed_skills`.

### Changes to `backend/app/api/deps.py`

- `get_board_for_actor_read` / `get_board_for_actor_write` updated to allow standalone agents with an `agent_board_access` grant to pass the board guard without being a board member.

---

## Phase 3 — Standalone Provisioning

**File:** `backend/app/services/openclaw/provisioning_db.py`

- `create_agent` now branches on `agent_type`. For `standalone`, it skips board assignment and does not emit board template files.
- A `STANDALONE_TEMPLATE_MAP` was added to `constants.py` with identity, soul, memory, tools, and heartbeat templates appropriate for a standalone (board-less) agent.
- `provisioning.py` selects the correct template map based on `agent_type`.

---

## Phase 4 — Webhook Dispatch

**File:** `backend/app/services/webhooks/dispatch.py`

- A new `dispatch_agent_webhook` function handles agent-scoped inbound webhook delivery. It:
  1. Looks up the `AgentWebhook` record from the `endpoint_path`.
  2. Verifies the HMAC signature if a secret is configured (rejects with `403` on mismatch).
  3. Writes a row to `agent_webhook_payloads`.
  4. Enqueues the agent for processing via the existing gateway queue.
- The ingest route at `POST /api/v1/agents/webhooks/ingest/{endpoint_path}` is public (no auth required) to allow external services to POST directly.

---

## Phase 5 — Frontend

### API layer

**`frontend/src/api/generated/model/agentRead.ts`** (modified)  
Added:
- `agent_type?: string`
- `installed_skills?: string[] | null`

**`frontend/src/api/generated/model/agentCreate.ts`** (modified)  
Added:
- `agent_type?: string`
- `gateway_id?: string | null`
- `installed_skills?: string[] | null`

**`frontend/src/api/standaloneAgents.ts`** (new)  
Hand-written API client (follows `customFetch` pattern used throughout the project) covering:
- `AgentWebhookRead`, `AgentWebhookCreate`, `AgentWebhookUpdate`, `AgentWebhookPayloadRead` types
- `listAgentWebhooks`, `createAgentWebhook`, `updateAgentWebhook`, `deleteAgentWebhook`, `listAgentWebhookPayloads`
- `AgentBoardAccessRead`, `AgentBoardAccessCreate` types
- `listAgentBoardAccess`, `createAgentBoardAccess`, `deleteAgentBoardAccess`
- `AgentSkillsRead`, `AgentSkillsUpdate` types
- `getAgentSkills`, `updateAgentSkills`

### Agents list (`frontend/src/app/agents/page.tsx`)

- **Type filter tabs** above the table: All / Standalone / Board Agents / Gateway Main, with live per-tab counts.
- `filterAgentsByType` helper maps the `board` tab to both `board_worker` and `board_lead` types.
- `AGENT_SORTABLE_COLUMNS` extended to include `agent_type`.

### Agents table (`frontend/src/components/agents/AgentsTable.tsx`)

- `AGENT_TYPE_CONFIG` map with label and colour per type:
  - `standalone` → purple
  - `board_lead` → blue
  - `board_worker` → slate
  - `gateway_main` → amber
- `AgentTypeBadge` component rendering a coloured pill.
- New **Type** column inserted after the agent name column.

### Agent create (`frontend/src/app/agents/new/page.tsx`)

- **Mode toggle** at the top of the create form: "Board Agent" or "Standalone".
- Selecting **Standalone** replaces the board picker with a gateway picker (populated from `useListGatewaysApiV1GatewaysGet`).
- `handleSubmit` branches on mode: standalone agents are submitted with `{ agent_type: "standalone", gateway_id }` instead of `{ board_id }`.
- Descriptive hint text rendered under the toggle explains each mode.

### Agent detail (`frontend/src/app/agents/[agentId]/page.tsx`)

For `agent_type === "standalone"` agents, the detail page renders a **tab bar** with five tabs:

| Tab | Content |
|---|---|
| Overview | Existing overview + health + activity grid (unchanged) |
| Files | `AgentFilesPanel` (existing component) |
| Webhooks | `AgentWebhooksPanel` (new) |
| Skills | `AgentSkillsPanel` (new) |
| Board access | `AgentBoardAccessPanel` (new) |

Non-standalone agents keep the existing layout (no tab bar; files toggle in the header).

### New panel components

#### `frontend/src/components/agents/AgentWebhooksPanel.tsx`
- Lists all webhooks for the agent with endpoint URL, enabled/disabled badge, and secret indicator.
- **Enable / Disable** toggle per webhook (PATCH `enabled`).
- **Edit** inline form: description, new secret (password input), signature header — save/cancel.
- **Delete** with confirmation via mutation.
- **Payloads** button opens a slide-up overlay showing the last 20 received payloads with timestamp and JSON body.
- Create webhook form (shown via "+ New webhook" button): description, optional secret, optional signature header.

#### `frontend/src/components/agents/AgentSkillsPanel.tsx`
- Displays the current `installed_skills` allowlist as removable pills.
- When `null` (gateway defaults), shows an explanatory empty state.
- **Add skill** via text input (Enter key or Add button).
- **Remove** individual skills by clicking `×` on the pill.
- **Reset to gateway defaults** button sets `installed_skills: null`.
- All mutations use TanStack Query with `invalidateQueries` on success.

#### `frontend/src/components/agents/AgentBoardAccessPanel.tsx`
- Lists boards the agent currently has access to with `Read` / `Write` badge.
- **Revoke** button per grant.
- **Grant access** form: board picker (populated from `useListBoardsApiV1BoardsGet`, pre-filtered to exclude already-granted boards) and access level dropdown.
- "Grant access" button only shown when ungranteed boards remain.

---

## Phase 6 — Agent-Scoped Self-Discovery API

**File:** `backend/app/api/agent.py` (extended)

New routes authenticated with the agent's own token (`X-Agent-Token`):

| Method | Path | Description |
|---|---|---|
| `GET` | `/agent/self` | Returns the agent's own record including `agent_type`, `installed_skills`, and resolved `gateway_id` |
| `GET` | `/agent/webhooks` | Returns the agent's own configured webhooks |
| `GET` | `/agent/boards` | Returns boards the agent has been granted access to (via `agent_board_access`) |
| `GET` | `/agent/boards/{board_id}/tasks` | Returns tasks on a granted board, respecting `access_level` |

Board access checks in `deps.py` were updated so the `_guard_board_access` dependency accepts standalone agents whose `agent_board_access` row grants sufficient access, in addition to the existing board-member check.

---

## Testing

### Backend
- Test coverage added for all new API routes in `backend/tests/`.
- 564 tests passing, `flake8` clean, `mypy --strict` clean at time of completion.

### Frontend
- 163 tests passing, `tsc --noEmit` clean, `eslint --max-warnings=0` clean.
- New panel components are not yet unit-tested (integration-level coverage only via TypeScript + build verification).

---

## Known Limitations / Future Work

1. **Webhook secret storage** — secrets are stored as plain text. Should be encrypted at rest (e.g. via a KMS-backed column or application-layer AES encryption).
2. **Standalone agents in channels** — excluded from Phase 1. Can be added later by allowing channel subscriptions independent of board membership.
3. **Quota limits** — max standalone agents per org and max webhooks per agent are not yet configurable. Should eventually be gated by plan/tier settings.
4. **`make api-gen`** — the two modified generated model files (`agentRead.ts`, `agentCreate.ts`) will be overwritten the next time `make api-gen` is run. The fields `agent_type`, `gateway_id`, and `installed_skills` need to be present in the backend's OpenAPI schema (they are) so they will be regenerated correctly.
5. **Standalone agent memory** — agent files serve as the current memory mechanism. A dedicated `agent_memory` table mirroring `board_memory` could be added if richer structured memory is needed.
