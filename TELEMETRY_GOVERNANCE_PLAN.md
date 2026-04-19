# Telemetry Enrichment & Enterprise Governance Plan

> **Status:** Draft  
> **Created:** 2026-04-03  
> **Last updated:** 2026-04-19  
> **Scope:** Enriching Product Foundry telemetry with OpenClaw pod data; agent audit trails; token/cost tracking; enterprise governance primitives.

---

## 1. Motivation

Product Foundry already stores activity events, agent heartbeats, approvals, channel messages, sprint lifecycle events, and planning artefacts — but the data flowing through the OpenClaw gateway (sessions, token usage, command logs, cost attribution) is largely opaque to operators. Channels, sprints, and MCP app invocations also generate events that lack structured audit coverage. Bridging these gaps enables:

- Full **agent audit trails** from provision to task completion.
- **Token and cost visibility** per agent, project, and organization.
- Enterprise **governance controls** (budgets, enhanced RBAC, data residency, compliance evidence).

---

## 2. Current State

### 2.1 What we have today

| Layer | Data available | Storage |
|---|---|---|
| **ActivityEvent** | `event_type`, `message`, `agent_id`, `task_id`, `board_id`, `created_at` — 35+ event types covering agent lifecycle, task status, sprints, planning, file writes/deletes, approvals, board lead notifications, gateway coordination | Postgres `activity_events` |
| **Agent model** | `status`, `agent_type` (`board_worker`/`board_lead`/`gateway_main`/`standalone`), `last_seen_at`, `heartbeat_config`, `identity_profile`, `identity_template`, `soul_template`, `installed_skills` (per-agent skill allow-list), `lifecycle_generation`, `wake_attempts`, `is_board_lead`, provisioning/delete confirmation flow fields, lifecycle timestamps | Postgres `agents` |
| **Approval model** | `action_type`, `payload`, `confidence`, `rubric_scores`, `status`, `resolved_at` | Postgres `approvals` |
| **Board model** | Goal metadata, workflow governance flags (`require_approval_for_done`, `require_review_before_done`, `comment_required_for_review`, `block_status_changes_with_pending_approval`, `only_lead_can_change_status`), `max_agents`, `is_platform`, `auto_advance_sprint` | Postgres `boards` |
| **Organization model** | `name`, `branding_overrides` | Postgres `organizations` |
| **OrganizationMember** | `role` (`owner`/`admin`/`member`), `all_boards_read`, `all_boards_write` — three-tier role hierarchy with `ROLE_RANK` (member=0, admin=1, owner=2). `OrganizationBoardAccess` provides per-project `can_read`/`can_write` scoping | Postgres `organization_members`, `organization_board_access` |
| **Channels & Threads** | Board-scoped messaging channels (`alert`/`discussion` types), threads linked to tasks, thread messages, agent subscriptions (`all`/`mentions`/`none`), per-user read state | Postgres `channels`, `threads`, `thread_messages`, `channel_subscriptions`, `user_channel_states` |
| **Sprints** | Lifecycle states (`draft`/`queued`/`active`/`completed`/`cancelled`), velocity snapshots (`committed_minutes`, `completed_minutes`, `actual_minutes`), sprint webhooks for lifecycle event notifications | Postgres `sprints`, `sprint_tickets`, `sprint_webhooks` |
| **Planning** | Plan items with decompose/promote-to-task flow | Postgres via plans API |
| **Skills** | Marketplace catalog with `name`, `description`, `category`, `risk`, `source_url`; skill packs (repo URLs for bulk sync); gateway installation tracking (`GatewayInstalledSkill`); per-agent `installed_skills` JSON allow-list | Postgres `marketplace_skills`, `skill_packs`, `gateway_installed_skills` |
| **Tags** | Org-scoped task classification with `name`, `slug`, `color` | Postgres `tags`, `tag_assignments` |
| **Custom Fields** | Per-board task field definitions and values | Postgres `task_custom_field_definitions`, `task_custom_field_values`, `board_task_custom_fields` |
| **Board Memory** | Board-level and group-level chat/context; supports `mcp_app_result` content type (charts) with `app_metadata` | Postgres `board_memory`, `board_group_memory` |
| **Gateway RPC** | Protocol v3 with 58+ methods across usage, sessions, config, exec/approvals, agents, files, skills, MCP apps, cron, node/device pairing, chat, TTS; 19 event types | Transient — fetched live per request, never persisted |
| **Dashboard metrics** | KPIs (`active_agents`, `inbox_tasks`, `in_progress_tasks`, `review_tasks`, `done_tasks`, `error_rate_pct`, `median_cycle_time_hours_7d`, `pending_approvals`), time-series (throughput, cycle_time, error_rate, WIP by status), range/project/group filtering | Computed on the fly from `activity_events` + `tasks` |
| **Webhooks** | Inbound classifier (GitHub Actions, PRs, deployments, test results → channels); outbound board/agent/sprint webhooks with retry | Postgres `board_webhooks`, `agent_webhooks`, `sprint_webhooks` + payload tables |
| **Agent Files** | Proxied gateway file CRUD (`agents.files.list/get/set/delete`); writes/deletes logged via `record_activity` with `agent.file.write`, `agent.file.delete` event types; `AUTH_TOKEN` values redacted | Gateway passthrough; templates persisted on Agent model |
| **Heartbeat** | Agent check-in updates `last_seen_at` | Postgres `agents` |
| **Queue** | Redis-backed list queue with two task types: `lifecycle_reconcile` (agent state machine) and `webhook` (outbound dispatch). Supports scheduled/delayed tasks and exponential backoff retry with jitter | Redis + Postgres |
| **OpenClaw hooks** | `command-logger` writes audit logs inside the pod | Pod-local filesystem only |

### 2.2 Gaps

1. **No persisted token/cost data** — `usage.cost` and `usage.status` are live gateway calls; there is no historical record.
2. **No per-agent cost attribution** — the gateway reports aggregate usage, not per-session or per-agent.
3. **No structured audit trail** — `activity_events` captures 35+ high-level event types but not the granular causal chain (prompt → tool call → approval → execution → result) and carries no token/cost enrichment.
4. **Command-logger output is pod-local** — audit logs from the `command-logger` hook stay on the pod filesystem and are not ingested into Product Foundry.
5. **Governance primitives partially addressed** — board-level workflow controls (approval gates, review requirements, lead-only status changes) and per-agent skill allow-lists exist, but there are no budget limits, model allow-lists, session TTL enforcement, or compliance export capabilities.
6. **Channel/thread/message activity not audited** — no `record_activity` calls for channel creation, thread creation, message posting, or subscription changes.
7. **Skill install/uninstall events not recorded** — skill lifecycle changes produce no activity events.
8. **MCP app invocations opaque** — `mcp.tools.call` passes through the gateway with no Product Foundry visibility or logging.

---

## 3. Data Sources in the OpenClaw Pod

These are the data streams we can tap into, ordered by integration effort:

### 3.1 Gateway RPC (already connected)

Protocol v3 exposes 58+ methods. Key categories for telemetry:

| Category | Methods | Data | Notes |
|---|---|---|---|
| **Usage** | `usage.status`, `usage.cost` | Token counters (used, max, per-model), accumulated cost | Poll periodically or on heartbeat |
| **Sessions** | `sessions.list`, `sessions.preview`, `sessions.patch`, `sessions.reset`, `sessions.delete`, `sessions.compact` | Session metadata, message counts, timestamps | Correlate sessions → agents |
| **Chat** | `chat.history`, `chat.send`, `chat.abort` | Full message log per session | Expensive; use selectively |
| **Config** | `config.get`, `config.set`, `config.apply`, `config.patch`, `config.schema` | Running gateway config | Compliance snapshots |
| **Exec / Approvals** | `exec.approvals.get`, `exec.approvals.set`, `exec.approval.request`, `exec.approval.resolve`, `exec.approvals.node.get`, `exec.approvals.node.set` | Approval rules and resolution | Governance evidence |
| **Agents** | `agents.list`, `agents.create`, `agents.update`, `agents.delete`, `agents.files.list`, `agents.files.get`, `agents.files.set` | Runtime agent config, state, workspace files | Cross-reference with DB agents |
| **Skills** | `skills.status`, `skills.bins`, `skills.install`, `skills.update` | Installed skills and availability | Track install/update events |
| **MCP Apps** | `mcp.tools.list`, `mcp.tools.call`, `mcp.resources.list`, `mcp.resources.read` | MCP tool invocations and resource access (protocol v3+) | New audit surface |
| **Cron** | `cron.list`, `cron.status`, `cron.add`, `cron.update`, `cron.remove`, `cron.run`, `cron.runs` | Scheduled tasks within gateway | Track automated actions |
| **Node / Device** | `node.pair.*`, `device.pair.*`, `device.token.*`, `node.list`, `node.invoke` | Multi-node coordination, device pairing | Security audit |
| **System** | `health`, `status`, `system-presence`, `system-event`, `logs.tail` | Health, presence, live logs | Real-time audit |

Gateway events (19 types): `connect.challenge`, `agent`, `chat`, `presence`, `tick`, `talk.mode`, `shutdown`, `health`, `heartbeat`, `cron`, `node.pair.requested`, `node.pair.resolved`, `node.invoke.request`, `device.pair.requested`, `device.pair.resolved`, `voicewake.changed`, `exec.approval.requested`, `exec.approval.resolved`.

### 3.2 OpenClaw Hook Outputs (requires new ingestion)

| Hook | Output | Path on pod |
|---|---|---|
| `command-logger` | Structured command audit logs (tool name, args, result, timestamp) | `~/.openclaw/logs/commands/` |
| `session-memory` | Memory checkpoint files | `~/.openclaw/workspace/memory/` |
| `boot-md` | Boot checklist results | Session-scoped |

### 3.3 Auth-Profiles / Provider Metadata (already written at provision)

| Source | Data |
|---|---|
| `auth-profiles.json` | Provider names, token expiry timestamps, usage stats (if provider populates) |
| Skill config envs | Per-skill credential metadata (non-secret) |

### 3.4 Internal Event Sources (no gateway RPC needed)

These data streams are generated within Product Foundry itself and should feed into the audit log:

| Source | Events | Current state |
|---|---|---|
| **Channels** | Channel creation, thread creation, message posting, subscription changes | Not logged via `record_activity` |
| **Sprints** | Sprint created/started/completed/cancelled/deleted, backlog task created | Already logged via `record_activity` |
| **Planning** | Plan created/deleted/archived, promoted to task, decompose requested | Already logged via `record_activity` |
| **Skills** | Marketplace skill CRUD, skill pack sync, gateway skill install/uninstall, agent skill allow-list changes | Not logged via `record_activity` |
| **Board governance** | Approval gate changes, review requirement changes, lead assignment | Not logged via `record_activity` |
| **MCP app results** | Chart renders, app metadata writes to board memory | Not logged; `mcp_app_result` content type visible in board memory only |

---

## 4. Agent Audit Trail

### 4.1 Design

Introduce a new `agent_audit_log` table that captures the full causal chain for every significant agent action:

```
agent_audit_log
├── id               UUID PK
├── organization_id  UUID FK → organizations
├── board_id         UUID FK → boards (nullable)  -- note: pending Board → Project rename
├── agent_id         UUID FK → agents
├── session_key      TEXT (openclaw session id)
├── thread_id        UUID FK → threads (nullable)  -- channel thread correlation
├── sprint_id        UUID FK → sprints (nullable)  -- sprint correlation
├── event_category   TEXT  -- 'lifecycle' | 'command' | 'chat' | 'approval' | 'cost' | 'config' | 'channel' | 'sprint' | 'planning' | 'skill' | 'mcp' | 'file'
├── event_action     TEXT  -- 'provision', 'tool_call', 'message_sent', 'approval_requested', 'thread_created', 'skill_installed', 'mcp_tool_called', 'sprint_started', 'plan_promoted', 'file_written', 'file_deleted', ...
├── detail           JSONB -- structured event payload
├── token_input      INT (nullable) -- prompt tokens consumed
├── token_output     INT (nullable) -- completion tokens consumed
├── cost_usd         NUMERIC(12,6) (nullable) -- estimated cost in USD
├── model_id         TEXT (nullable) -- model used for this action
├── correlation_id   TEXT (nullable) -- groups related events (e.g. a task execution chain)
├── source           TEXT  -- 'product_foundry' | 'gateway_rpc' | 'command_logger' | 'webhook'
├── actor_type       TEXT  -- 'agent' | 'user' | 'system'
├── actor_id         UUID (nullable)
├── ip_address       TEXT (nullable)
├── created_at       TIMESTAMPTZ DEFAULT now()
```

### 4.2 Ingestion Paths

```
                                ┌───────────────────┐
                                │  OpenClaw Pod      │
                                │  ┌─────────────┐   │
                                │  │ Gateway WS   │──── usage.cost / usage.status
                                │  └─────────────┘   │  (periodic poll or event push)
                                │  ┌─────────────┐   │
                                │  │ cmd-logger   │──── command audit log files
                                │  └─────────────┘   │  (new: sidecar → PF ingest API)
                                └───────────────────┘
                                          │
                        ┌─────────────────┼─────────────────┐
                        ▼                 ▼                 ▼
                ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
                │ Poll Worker  │  │ Ingest API   │  │ Webhook      │
                │ (RQ cron)    │  │ POST /ingest │  │ POST /wh     │
                └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
                       │                 │                 │
                       └─────────────────┼─────────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │                             │
                          │  ┌───────────────────────┐  │
                          │  │  Internal Events      │  │
                          │  │  (channels, sprints,  │  │
                          │  │   skills, planning)   │  │
                          │  └───────────┬───────────┘  │
                          │              │              │
                          │              ▼              │
                          │    ┌───────────────────┐    │
                          │    │  agent_audit_log   │    │
                          │    │  (Postgres)        │    │
                          │    └───────────────────┘    │
                          │                             │
                          │     Product Foundry         │
                          └─────────────────────────────┘
```

### 4.3 Implementation Phases

**Phase 1 — Periodic usage snapshots (low effort, high value)**
1. Add RQ periodic job (e.g. every 5 min) that calls `usage.status` + `usage.cost` per gateway. The existing queue infrastructure (Redis-backed with scheduled task support) supports this pattern.
2. Store snapshots in a new `usage_snapshots` table keyed by `(gateway_id, agent_id, captured_at)`.
3. Dashboard widget: token usage over time, cost per agent sparkline — following existing range/filter conventions (`24h`/`3d`/`7d`/`14d`/`1m`/`3m`/`6m`/`1y` with `board_id`/`group_id` scoping).

**Phase 2 — Audit log from existing activity events**
1. Create `agent_audit_log` table (migration).
2. Extend `record_activity()` to dual-write into `agent_audit_log` with `source='product_foundry'`. Note: `record_activity` already covers 35+ event types across agent lifecycle, tasks, sprints, planning, approvals, file writes/deletes, and board lead notifications — so the dual-write captures substantial ground immediately.
3. Add `record_activity` calls to currently un-logged events: channel/thread creation and messages, skill installs/uninstalls, MCP app calls, board governance setting changes.
4. Enrich heartbeat endpoint to optionally accept `token_input`/`token_output` so agents can self-report.
5. Optional: backfill `agent_audit_log` from existing `activity_events` rows for historical continuity.

**Phase 3 — Command-logger ingestion**
1. Add sidecar or init-container in the OpenClaw pod that tails `~/.openclaw/logs/commands/` and POSTs to a new `POST /api/v1/agent/ingest/commands` endpoint.
2. Alternatively, add a new OpenClaw hook that POSTs directly to Product Foundry on each command execution (requires upstream hook support).
3. Parse command-logger JSON → `agent_audit_log` rows with `source='command_logger'`, `event_category='command'`.

**Phase 4 — Real-time event stream**
1. Subscribe to gateway events (`system-event`, `tick`, `heartbeat`, `exec.approval.requested`, `exec.approval.resolved`, etc.) via a persistent WebSocket listener (background worker).
2. Normalize events → `agent_audit_log`.
3. Expose SSE endpoint for live audit trail in the UI.

---

## 5. Token & Cost Tracking

### 5.1 Data Model

```
usage_snapshots
├── id               UUID PK
├── organization_id  UUID FK
├── gateway_id       UUID FK
├── agent_id         UUID FK (nullable — null = gateway aggregate)
├── session_key      TEXT (nullable)
├── model_id         TEXT
├── prompt_tokens    BIGINT
├── completion_tokens BIGINT
├── total_tokens     BIGINT
├── cost_usd         NUMERIC(12,6)
├── snapshot_type    TEXT  -- 'periodic' | 'session_end' | 'agent_report'
├── captured_at      TIMESTAMPTZ
```

### 5.2 Cost Attribution Strategy

| Level | How |
|---|---|
| **Per gateway** | `usage.cost` RPC → aggregate row with `agent_id = NULL` |
| **Per agent** | Future: if gateway supports per-session cost, map `session_key → agent.openclaw_session_id` |
| **Per task** | Correlate audit log `correlation_id` (set to `task_id`) with usage rows in the same time window |
| **Per model** | `usage.status` returns per-model counters; store as separate rows |
| **Per sprint** | Correlate `sprint_id` in audit log with usage rows for sprint duration window |

### 5.3 Frontend

- **Agent detail page**: token usage chart (stacked by model), cumulative cost counter.
- **Dashboard KPI**: total org spend in selected range, cost delta % — following the existing range selector pattern (`24h` through `1y`).
- **Project view**: cost summary per project (sum of agent costs).
- **Sprint view**: cost incurred during sprint window, cost-per-story-point if velocity data available.
- **Alerts**: configurable threshold (e.g. "agent X exceeded $50/day").

---

## 6. Enterprise Features

### 6.1 Budget Controls

| Feature | Description | Implementation |
|---|---|---|
| **Org budget cap** | Hard or soft monthly spend limit per organization | New `settings JSONB` column on `organizations` with `monthly_budget_usd` |
| **Project budget cap** | Per-project spend ceiling | New `budget_usd` column on `boards` |
| **Agent budget cap** | Per-agent spend ceiling before auto-pause | New `budget_usd` column on `agents` |
| **Budget alerts** | Webhook/email/channel notification at 50%, 80%, 100% | RQ job checks `usage_snapshots` vs caps; can post to alert channels |
| **Auto-pause on cap** | Agent status → `budget_paused` when ceiling hit | Lifecycle orchestrator checks budget before wake |

### 6.2 Role-Based Access Control (RBAC)

**Current state:** The `role` column already exists on `organization_members` with values `owner`, `admin`, `member`. A `ROLE_RANK` hierarchy (`member=0`, `admin=1`, `owner=2`) is defined in the organizations service. `ADMIN_ROLES = {"owner", "admin"}` gates administrative actions via `require_org_admin`. Per-project access is scoped through `OrganizationBoardAccess` (`can_read`/`can_write`) and member-level `all_boards_read`/`all_boards_write` flags.

**Proposed extension** — add two new roles to the existing hierarchy:

| Role | Rank | Permissions |
|---|---|---|
| **owner** | 4 | Full control, billing, member management |
| **admin** | 3 | Gateway management, agent lifecycle, project CRUD |
| **operator** | 2 | Agent management within assigned projects, approval resolution |
| **viewer** | 1 | Read-only dashboard, activity feed, audit trail |
| **auditor** | 1 | Read-only access to audit logs, usage data, compliance exports — no operational actions |

Implementation:
1. Extend `ROLE_RANK` in `organizations.py` with `operator=2`, `viewer=1`, `auditor=1`.
2. Replace `require_org_admin` with `require_role(min_role=...)` dependency using rank-based comparison (infrastructure for rank comparison already exists).
3. Frontend: role-aware navigation hiding/showing admin sections.

### 6.3 Audit & Compliance

| Feature | Description |
|---|---|
| **Immutable audit log** | `agent_audit_log` is append-only; no UPDATE/DELETE API surface |
| **Audit export** | `GET /api/v1/audit/export?format=csv&range=30d` for SOC2/ISO evidence |
| **Retention policy** | Configurable per-org retention period; RQ job prunes older rows |
| **Config snapshots** | Periodic `config.get` snapshots stored for change tracking |
| **Approval evidence chain** | Link `approval.id` → `agent_audit_log.correlation_id` so every approval can be traced to the triggering command and resulting execution |

### 6.4 Data Residency & Isolation

| Feature | Description |
|---|---|
| **Org-scoped data partitioning** | All new tables include `organization_id`; queries always filter by org |
| **Gateway allow-list** | Admin-configurable allowed gateway URLs per org (prevent rogue gateways) |
| **Secret rotation reminders** | Track `auth-profiles.json` token expiry; alert before provider tokens expire |
| **PII redaction** | Optional redaction filter on `agent_audit_log.detail` before storage for sensitive payloads (note: agent files API already redacts `AUTH_TOKEN` values) |
| **Thread privacy** | Support channel ACL with `owner_board_id` on threads for private/scoped conversations |

### 6.5 Agent Governance Policies

| Policy | Description | Enforcement |
|---|---|---|
| **Max agents per project** | Prevent runaway agent creation | Already exists: `Board.max_agents` column (default 1) and `AgentCreateLimitService`. Extend to configurable per-org override |
| **Mandatory approval for high-risk actions** | Require human sign-off for destructive commands | Extend `exec.approvals` integration; Product Foundry stores policy, gateway enforces. Board-level approval gates already exist (`require_approval_for_done`, `block_status_changes_with_pending_approval`) |
| **Model allow-list** | Restrict which LLM models agents can use | New `allowed_models` in org settings JSONB; checked at provision time via `config.set`. Gateway `models.list` method available for validation |
| **Session TTL / compaction policy** | Enforce max session age before forced compaction/reset | Org-level setting; RQ job calls `sessions.compact` for stale sessions |
| **Skill allow-list / deny-list** | Control which skills can be installed | Per-agent: `Agent.installed_skills` already exists as a JSON allow-list. Per-org: add `skill_deny_list` to org settings JSONB. `MarketplaceSkill.risk` field supports risk-based gating (e.g. block `high` risk skills without admin approval) |

---

## 7. API Surface (New Endpoints)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/audit` | Paginated agent audit trail with filters (agent, project, category, date range) |
| `GET` | `/api/v1/audit/export` | CSV/JSON export of audit records for compliance |
| `GET` | `/api/v1/usage` | Aggregated token/cost data by org, project, agent, model, time range |
| `GET` | `/api/v1/usage/agents/{agent_id}` | Per-agent usage history |
| `POST` | `/api/v1/agent/ingest/commands` | Ingest command-logger output from pod sidecar |
| `POST` | `/api/v1/agent/ingest/usage` | Agent self-reported usage (token counts per turn) |
| `GET` | `/api/v1/governance/policies` | List org governance policies |
| `PUT` | `/api/v1/governance/policies` | Update org governance policies (budget, model allow-list, etc.) |
| `GET` | `/api/v1/governance/budgets` | Budget status (current spend vs caps at org/project/agent level) |

---

## 8. Database Migrations

| Migration | Tables / Columns |
|---|---|
| **M1** | `CREATE TABLE agent_audit_log (...)` — includes `thread_id`, `sprint_id` FKs and expanded `event_category` values |
| **M2** | `CREATE TABLE usage_snapshots (...)` |
| **M3** | `ALTER TABLE organizations ADD COLUMN settings JSONB DEFAULT '{}'` (budget caps, retention, model allow-list, skill deny-list) |
| **M4** | `ALTER TABLE boards ADD COLUMN budget_usd NUMERIC(12,6)` |
| **M5** | `ALTER TABLE agents ADD COLUMN budget_usd NUMERIC(12,6)` |
| **M6** | ~~`ALTER TABLE organization_members ADD COLUMN role`~~ — **already exists**. Instead: extend `ROLE_RANK` in service code to add `operator`, `viewer`, `auditor` roles (code change, no migration needed) |
| **M7** | `ALTER TABLE organizations.settings` to include `skill_deny_list` schema — org-level skill deny-list. Note: per-agent skill allow-list already exists via `Agent.installed_skills`; per-project `Board.max_agents` already exists |

---

## 9. Rollout Plan

| Phase | Scope | Estimated Effort |
|---|---|---|
| **Phase 1** | Usage snapshots table + RQ poll job + dashboard cost widget | 1 sprint |
| **Phase 2** | `agent_audit_log` table + dual-write from `record_activity` + extend `record_activity` to channels/skills/MCP + audit list API + frontend audit trail page | 1–2 sprints |
| **Phase 3** | Command-logger ingestion (sidecar or hook) + real-time event subscription | 1–2 sprints |
| **Phase 4** | RBAC role extension (`operator`/`viewer`/`auditor`) + governance policy CRUD + budget controls + auto-pause | 2 sprints |
| **Phase 5** | Compliance export + retention policy + config snapshot tracking + PII redaction | 1 sprint |
| **Phase 6** | Org-level skill deny-list enforcement + model allow-list + session TTL governance | 1 sprint |

---

## 10. Open Questions

1. **Gateway per-session cost** — Does the OpenClaw gateway expose per-session token counts, or only aggregate? If aggregate-only, we need agent self-reporting (Phase 2 enrichment on heartbeat).
2. **Command-logger format** — What is the exact JSON schema of `command-logger` output? Need a sample to build the parser.
3. **Event push vs poll** — Can we subscribe to a gateway event stream for `usage` changes, or must we poll? The gateway exposes 19 event types via WebSocket — is per-method cost data included in any of them?
4. **Multi-gateway cost normalization** — Different gateways may use different models/providers. How do we normalize cost to a single currency?
5. **Audit log retention at scale** — At high event volumes, should we partition `agent_audit_log` by month, or use a time-series engine?
6. **Upstream hook API** — Would OpenClaw accept a new webhook-push hook type that POSTs command logs directly to a configurable URL (eliminating the sidecar)?
7. **Channel message volume** — At scale, channel threads can generate high event volume. Should thread messages be sampled, or should only metadata (message count, sender, timestamp) be logged rather than full content?
8. **MCP app audit granularity** — Should every `mcp.tools.call` be individually logged, or only failures / high-cost calls? Need to balance audit completeness vs storage cost.
9. **Sprint velocity ↔ cost correlation** — Should velocity snapshots (`committed_minutes`, `completed_minutes`) feed into cost attribution to calculate cost-per-story-point or cost-per-sprint metrics?

---

## 11. Dependencies

| Dependency | Owner | Notes |
|---|---|---|
| OpenClaw gateway `usage.status` / `usage.cost` response shape | OpenClaw core | Need documentation or sample payloads |
| `command-logger` hook output format | OpenClaw core | Need JSON schema |
| Gateway event subscription (persistent WS) | Product Foundry backend | New background worker pattern |
| RQ periodic scheduler | Already available | Used for lifecycle reconcile; extend for usage polling |
| Frontend cost/audit pages | Frontend team | New pages under `/audit` and `/usage` |
| Board → Project rename | See `PROJECT_RENAME_PLAN.md` | Once Phase 1 lands, user-facing references change from "Board" to "Project". DB column remains `board_id` until Phase 3 of rename plan |
