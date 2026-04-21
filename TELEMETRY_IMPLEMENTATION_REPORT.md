# Telemetry Governance Implementation Report

> **Status:** Foundational backend complete (Phase 1–3/6 shipped; Phase 4–6 deferred)  
> **Date:** 2026-04-20  
> **Scope:** All 6 phases of the Telemetry Enrichment & Enterprise Governance Plan  
> **Test result:** 622 passed, 1 xfailed, 0 failures

---

## Summary

This report documents the foundational backend implementation of `TELEMETRY_GOVERNANCE_PLAN.validated.md`, covering the shipped telemetry, audit, ingest, RBAC, and governance primitives while noting deferred enforcement and UI work.

---

## Changes Made

### Database Migrations (5 new files)

| File | Description |
|---|---|
| [migrations/versions/t0a1b2c3d4e5_merge_heads_for_telemetry.py](backend/migrations/versions/t0a1b2c3d4e5_merge_heads_for_telemetry.py) | Chains telemetry migrations from `a5c1e2f3b4d6` (content-type-metadata) |
| [migrations/versions/t1a2b3c4d5e6_m1_create_agent_audit_log.py](backend/migrations/versions/t1a2b3c4d5e6_m1_create_agent_audit_log.py) | Creates `agent_audit_log` — append-only structured audit trail with 8 indexes |
| [migrations/versions/t2b3c4d5e6f7_m2_create_usage_snapshots.py](backend/migrations/versions/t2b3c4d5e6f7_m2_create_usage_snapshots.py) | Creates `usage_snapshots` — cumulative token/cost snapshots per gateway/model |
| [migrations/versions/t3c4d5e6f7a8_m3_add_org_settings.py](backend/migrations/versions/t3c4d5e6f7a8_m3_add_org_settings.py) | Adds `organizations.settings` JSONB for governance config |
| [migrations/versions/t4d5e6f7a8b9_m4_m5_add_budget_usd.py](backend/migrations/versions/t4d5e6f7a8b9_m4_m5_add_budget_usd.py) | Adds `budget_usd` to `boards` and `agents` |

All migrations are idempotent (guarded with `_has_table` / `_has_column` checks). Migration head: `t4d5e6f7a8b9`.

---

### New Models

| File | Table | Purpose |
|---|---|---|
| [backend/app/models/agent_audit_log.py](backend/app/models/agent_audit_log.py) | `agent_audit_log` | Append-only audit trail. FKs to organizations (`ON DELETE CASCADE`), gateways/boards/agents/tasks/threads/sprints (`ON DELETE SET NULL`). |
| [backend/app/models/usage_snapshots.py](backend/app/models/usage_snapshots.py) | `usage_snapshots` | Per-model cumulative usage snapshots from gateway polls |

Both models are registered in [backend/app/models/__init__.py](backend/app/models/__init__.py).

---

### Extended Models

| Model | Column Added | Purpose |
|---|---|---|
| `Organization` | `settings: JSON` | Governance config (budgets, model allow-lists, skill deny-list, session TTL, retention). Note: stored as `JSON`, not `JSONB`. |
| `Board` | `budget_usd: Numeric(12,6)` | Per-project spend cap |
| `Agent` | `budget_usd: Numeric(12,6)` | Per-agent spend cap |

---

### New Schemas

| File | Contents |
|---|---|
| [backend/app/schemas/audit.py](backend/app/schemas/audit.py) | `AuditLogRead`, `CommandIngestItem`, `CommandIngestRequest`, `UsageIngestRequest` |
| [backend/app/schemas/usage.py](backend/app/schemas/usage.py) | `UsageSnapshotRead`, `UsageSummary`, `UsageAgentSummary`, `UsageModelBreakdown`, `UsageDashboard` |
| [backend/app/schemas/governance.py](backend/app/schemas/governance.py) | `OrgGovernanceSettings`, `OrgGovernanceSettingsUpdate`, `BudgetStatus`, `ProjectBudgetStatus`, `AgentBudgetStatus`, `GovernancePolicyRead` |

---

### Extended Services

#### `activity_log.py` — Dual-write to audit trail

[backend/app/services/activity_log.py](backend/app/services/activity_log.py) now exposes:

- **`record_activity()`** — backward-compatible with all existing callers. Any call that now passes `organization_id` will also dual-write an `AgentAuditLog` row. The event category is inferred automatically from the `event_type` prefix (e.g. `agent.*` → `lifecycle`, `sprint.*` → `sprint`, `skill.*` → `skill`).
- **`record_audit()`** — new function for writing directly to `agent_audit_log` without a legacy `ActivityEvent` row. Used in `channels.py` (channel creation), `skills_marketplace.py` (skill install/uninstall), and directly in the ingest API handlers.

#### Phase 1 — Usage Poll Worker

| File | Purpose |
|---|---|
| [backend/app/services/telemetry/__init__.py](backend/app/services/telemetry/__init__.py) | Package marker |
| [backend/app/services/telemetry/usage_poll_queue.py](backend/app/services/telemetry/usage_poll_queue.py) | `TASK_TYPE = "usage_poll"`, `enqueue_usage_poll()`, `requeue_usage_poll_task()` |
| [backend/app/services/telemetry/usage_poll_worker.py](backend/app/services/telemetry/usage_poll_worker.py) | `process_usage_poll_task()` — iterates all gateways, calls `usage.status` + `usage.cost`, persists `UsageSnapshot` rows, re-enqueues itself after `USAGE_POLL_INTERVAL_SECONDS` (900 s) |

The `usage_poll` task type is wired into [backend/app/services/queue_worker.py](backend/app/services/queue_worker.py) as `_TASK_HANDLERS["usage_poll"]`. Trigger the first poll by calling `enqueue_usage_poll()` once at startup or via an admin action.

---

### New API Endpoints

#### `GET /api/v1/audit` — Audit log listing
`GET /api/v1/audit` → `DefaultLimitOffsetPage[AuditLogRead]`  
Filters: `agent_id`, `board_id`, `event_category`, `source`, `since`, `until`.  
Requires: `owner | admin | operator | auditor` role.

#### `GET /api/v1/audit/export` — Compliance export  
`GET /api/v1/audit/export?format=csv|json`  
Returns a downloadable CSV or JSON file (Content-Disposition header set).  
Requires: `owner | admin | auditor` role.

#### `GET /api/v1/usage` — Usage dashboard  
`GET /api/v1/usage` → `UsageDashboard`  
Filters: `since`, `until`, `board_id` (resolves agent IDs on that board and narrows snapshots).  
Requires: any org member.

#### `GET /api/v1/usage/agents/{agent_id}` — Per-agent history  
Returns up to 200 most recent `UsageSnapshot` rows for a specific agent.

#### `POST /api/v1/agent/ingest/commands` — Command-logger ingest  
Accepts `CommandIngestRequest` from pod sidecars (via `X-Agent-Token`) or operators (via bearer). Agent callers automatically resolve `organization_id` and `gateway_id` from their authenticated record. Stores `AgentAuditLog` rows with `source='command_logger'`. Legacy `/api/v1/ingest/commands` remains as a compatibility alias.

#### `POST /api/v1/agent/ingest/usage` — Agent self-reported usage  
Accepts `UsageIngestRequest` from agents via `X-Agent-Token`. Stores `UsageSnapshot` rows with `snapshot_type='agent_report'`, fully attributed with `agent_id` and `gateway_id` from the authenticated agent. Operator-submitted (no agent token) payloads require a future gateway_id field and are silently no-op'd until that is added. Legacy `/api/v1/ingest/usage` remains as a compatibility alias.

#### `GET /api/v1/governance/policies` — Read governance settings  
Returns `GovernancePolicyRead` parsed from `organizations.settings`.

#### `PUT /api/v1/governance/policies` — Update governance settings  
Accepts `OrgGovernanceSettingsUpdate`. Persists to `organizations.settings`. Requires admin.  
Configurable: `monthly_budget_usd`, `allowed_models`, `skill_deny_list`, `session_ttl_hours`, `audit_retention_days`.

#### `GET /api/v1/governance/budgets` — Budget utilization  
Returns `BudgetStatus` with org, project, and agent spend vs. cap comparisons.

All routes are registered in [backend/app/main.py](backend/app/main.py) with OpenAPI tags.

---

### RBAC Extension

[backend/app/services/organizations.py](backend/app/services/organizations.py) now defines:

```
ROLE_RANK = {"viewer": -1, "auditor": -1, "member": 0, "operator": 0, "admin": 1, "owner": 2}
VALID_ROLES = {"owner", "admin", "operator", "member", "viewer", "auditor"}
```

Plus named capability sets replacing raw role checks:

| Capability | Roles |
|---|---|
| `CAPABILITY_MANAGE_ORG_ROLES` | owner, admin |
| `CAPABILITY_MANAGE_AGENTS_ROLES` | owner, admin, operator |
| `CAPABILITY_RESOLVE_APPROVALS_ROLES` | owner, admin, operator |
| `CAPABILITY_VIEW_AUDIT_ROLES` | owner, admin, operator, auditor |
| `CAPABILITY_EXPORT_COMPLIANCE_ROLES` | owner, admin, auditor |
| `CAPABILITY_READ_BOARDS_ROLES` | all roles |

- `normalize_role()` now validates the role against `VALID_ROLES` and raises HTTP 422 for unsupported values, preventing injection of arbitrary roles via invite/member mutation paths.
- `require_ingest_caller` — accepts both `X-Agent-Token` (agent/sidecar) and user bearer token; resolves `organization_id`, `agent_id`, and `gateway_id` from the authenticated agent record

---

### Audit Logging Added to Existing Endpoints

| Location | Event logged |
|---|---|
| [backend/app/api/skills_marketplace.py](backend/app/api/skills_marketplace.py) `_run_marketplace_skill_action` | `skill.installed` / `skill.uninstalled` — with `skill_id`, `skill_name`, `gateway_id`, actor |
| [backend/app/api/channels.py](backend/app/api/channels.py) `create_board_channel` | `channel.created` — with `channel_id`, `name`, `channel_type` |
| [backend/app/api/channels.py](backend/app/api/channels.py) subscription/read/mute handlers | `channel.subscription.upserted`, `channel.subscription.deleted`, `channel.read`, `channel.mute.toggled` |
| [backend/app/api/threads.py](backend/app/api/threads.py) `create_channel_thread` | `thread.created` — with `channel_id`, `topic`, actor |
| [backend/app/api/thread_messages.py](backend/app/api/thread_messages.py) message handlers | `thread.message.posted`, `thread.message.edited`, `thread.message.deleted` |

---

## Correctness Fixes (Second Pass)

The following bugs/gaps were found in review and corrected:

| Fix | File | Detail |
|---|---|---|
| Migration missing `thread_id` FK | [t1…audit_log.py](backend/migrations/versions/t1a2b3c4d5e6_m1_create_agent_audit_log.py) | Added `ON DELETE SET NULL` FK for `thread_id → threads.id` to match model |
| Ingest endpoints used human-only auth | [ingest.py](backend/app/api/ingest.py) | Replaced `require_org_member` with `require_ingest_caller` (accepts `X-Agent-Token` or user bearer) |
| Ingest wrote fake gateway UUID | [ingest.py](backend/app/api/ingest.py) | `ingest_usage` now resolves real `gateway_id` and `agent_id` from authenticated agent record |
| Usage `board_id` filter was accepted but not applied | [usage.py](backend/app/api/usage.py) | Added sub-query that resolves agent IDs on the board and filters snapshots |
| Budget endpoint leaked cross-org agents | [governance.py](backend/app/api/governance.py) | `all_agents_stmt` now scoped to boards in the active organization |
| RBAC `normalize_role()` accepted arbitrary roles | [organizations.py](backend/app/services/organizations.py) | Added VALID_ROLES guard — raises HTTP 422 for unknown roles |
| New dep `require_ingest_caller` added | [deps.py](backend/app/api/deps.py) | Returns `IngestCallerContext(organization_id, agent_id, gateway_id)` |
| Usage dashboard overcounted cumulative snapshots | [usage.py](backend/app/api/usage.py) | Replaced raw sums with time-window delta rollups for cumulative snapshot series |
| Budget endpoint used lifetime raw sums | [governance.py](backend/app/api/governance.py) | Budgets now use current-month rollups and safe unattributed gateway spend for uniquely mapped boards |
| First usage poll required manual seeding | [main.py](backend/app/main.py) | App lifespan now enqueues the initial `usage_poll` task on startup |

---

## Architecture Diagram

```
OpenClaw Pod
  ├── usage.status / usage.cost  ──► Usage Poll Worker (RQ, 15 min interval)
  │                                       └──► usage_snapshots (Postgres)
  └── command-logger output ──► POST /api/v1/agent/ingest/commands
                                      └──► agent_audit_log (source=command_logger)

Product Foundry API
  ├── record_activity() ──────────► activity_events (legacy) +
  │                                 agent_audit_log (dual-write when org_id set)
  ├── record_audit() ─────────────► agent_audit_log (direct)
  ├── GET /api/v1/audit ──────────► agent_audit_log
  ├── GET /api/v1/usage ──────────► usage_snapshots
  ├── PUT /api/v1/governance ─────► organizations.settings
  └── GET /api/v1/governance/budgets ► usage_snapshots + agents + boards
```

---

## Remaining Work (Future Phases)

The following items from the plan are NOT yet implemented and remain as follow-on work:

| Item | Phase | Notes |
|---|---|---|
| Extend existing `record_activity` call-sites to pass `organization_id` | Phase 2 | ~50+ callsites; non-breaking since the param is optional |
| Board governance setting change audit events | Phase 2 | Add to `app/api/boards.py` `update_board` handler |
| Real-time gateway event subscription (WebSocket listener) | Phase 4 | New background listener pattern |
| Budget auto-pause enforcement (`budget_paused` agent status) | Phase 4 | Lifecycle orchestrator check |
| Model allow-list enforcement at provision time | Phase 6 | Check `org.settings.allowed_models` in provisioning service |
| Skill deny-list enforcement at install time | Phase 6 | Check `org.settings.skill_deny_list` in `_run_marketplace_skill_action` |
| Session TTL scheduled compaction job | Phase 6 | New queue task calling `sessions.compact` for stale sessions |
| Audit log retention pruning job | Phase 5 | Scheduled delete of rows older than `audit_retention_days` |
| PII redaction filter on `agent_audit_log.detail` | Phase 5 | Optional middleware on ingest paths |
| SSE live audit trail endpoint | Phase 4 | Follow `activity.py` SSE pattern |
| Frontend pages: `/audit`, `/usage`, `/governance` | All phases | New Next.js pages |

---

## Test Evidence

```
622 passed, 1 xfailed, 4 warnings
```

All pre-existing tests pass unchanged. No regressions introduced. The `record_activity()` signature is fully backward-compatible (all new parameters are keyword-only with defaults).
