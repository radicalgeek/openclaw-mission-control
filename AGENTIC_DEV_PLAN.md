# OpenClaw Agentic Development System — Implementation Plan

> **Source:** Architecture plan from an external agent, adapted for the actual OpenClaw runtime and Mission Control codebases.
>
> **Scope:** This is an implementation plan for new features to be built into the platform. It covers new agent types, webhook-triggered standalone agents, and workflow orchestration.

---

## Table of Contents

1. [Overview](#overview)
2. [Codebase Context](#codebase-context)
3. [Feature 1: New Agent Types](#feature-1-new-agent-types)
4. [Feature 2: Webhook-Triggered Standalone Agents](#feature-2-webhook-triggered-standalone-agents)
5. [Hardware & Model Infrastructure](#hardware--model-infrastructure)
6. [Agent Roster](#agent-roster)
7. [Sprint Workflow](#sprint-workflow)
8. [Model Configuration](#model-configuration)
9. [Cost Strategy](#cost-strategy)
10. [Data Files Required](#data-files-required)
11. [Still To Be Configured](#still-to-be-configured)
12. [Implementation Sequence](#implementation-sequence)

---

## Overview

This system uses OpenClaw agents, managed through Mission Control, to perform software development autonomously. The agents write code, write tests, review each other's work, and deploy through CI/CD.

**Core approach:**
- **Acceptance Test Driven Development (ATDD)** — tests first, implementation second
- Local free models do bulk work; paid models act as quality gates at sprint checkpoints

**Two categories of work in this plan:**
1. **Platform features to build** — new agent types, webhook-triggered standalone agents (changes to this codebase)
2. **Workflow configuration** — board setup, agent provisioning, template customisation, skill creation (using existing platform features)

---

## Codebase Context

### What Exists Today

**Mission Control** (`openclaw-mission-control`):
- Agent types: `board_worker`, `board_lead`, `gateway_main`, `standalone` — stored as `String(32)` column, no DB enum
- `VALID_AGENT_TYPES` frozenset in `backend/app/schemas/agents.py` — defined but **not enforced** (no `field_validator` exists; any string is accepted)
- Agent webhooks: exist for standalone agents only — hardcoded check in `backend/app/api/agent_webhooks.py` line 116
- Webhook delivery: inbound POST → Redis queue → dispatch worker → sends message to agent's OpenClaw session via gateway
- Agent lifecycle: `StandaloneAgentLifecycleManager` handles standalone provisioning separately from board agents
- Template system: Jinja2 templates in `backend/templates/` rendered with per-agent context
- The heartbeat template is the agent's operational loop (not just a health check):
  - Workers: check in → pick task → execute → post comments → move to review
  - Leads: rebuild context → enforce rules → manage assignments → unblock
  - Main: check in → handle cross-board coordination
- Boards, tasks, sprints, channels, plans, memory, approvals — all exist
- Agent behaviour is defined by rendered templates (SOUL.md, HEARTBEAT.md, TOOLS.md, IDENTITY.md, AGENTS.md, USER.md, MEMORY.md, BOOTSTRAP.md) pushed to the gateway workspace
- Template override cascade: per-agent → per-board → org-wide → built-in .j2 file on disk

**OpenClaw Runtime** (`~/Code/openclaw`):
- **Does not know about `agent_type`** — this is purely a Mission Control concept
- The runtime treats all agents identically — sessions, workspaces, tools
- Config types in `src/config/types.models.ts` define `ModelDefinitionConfig` with `cost: { input, output, cacheRead, cacheWrite }` and `input: Array<"text" | "image">`
- `ModelsConfig` supports `mode: "merge" | "replace"` and `providers: Record<string, ModelProviderConfig>`
- Agent config in `src/config/types.agents.ts` supports `model`, `heartbeat`, `skills`, `tools`, `sandbox`, `runtime`, etc.
- Skills are SKILL.md files in workspace directories; the runtime discovers and loads them
- Agent workspaces are gateway-managed, not static filesystem directories
- Config lives at `~/.openclaw/openclaw.json` — this configures model providers and agent-to-model routing on the gateway side

### Existing Bugs / Inconsistencies To Fix

The following issues already exist and should be fixed while touching these areas:

1. **`list_self_webhooks()` response model** — in `backend/app/api/agent.py`, the declared response model appears wrong. Fix while updating the self-endpoints.
2. **`validate_standalone_board_id()` is one-way** — enforces "standalone must not have `board_id`" but does not enforce that board-scoped types **must** have a `board_id`. Non-standalone agents can currently be created without a board.
3. **`access_level` on board grants** — `_guard_board_access()` does not meaningfully enforce the `access_level` field; any grant effectively passes. If read-only vs read-write semantics matter for review agents accessing boards, this needs a follow-up.

### What Changes Are Required

Two new features need to be built into this codebase before the full workflow can operate:

---

## Feature 1: New Agent Types

### Purpose

The current four agent types are too coarse for a structured development workflow. The plan calls for specialised agent roles that the platform should recognise as first-class types. This enables:
- Role-specific provisioning logic and template selection
- UI filtering and management by role
- API-level role enforcement (e.g., only a `test_agent` can be assigned test-writing tasks)
- Better observability — dashboards can show agent activity by role

### New Types To Add

| Type Constant | `agent_type` Value | Board-Scoped? | Description |
|---|---|---|---|
| `AGENT_TYPE_PLANNING` | `planning` | Yes | Works with user to define features, decomposes into tickets |
| `AGENT_TYPE_SPRINT_PLANNING` | `sprint_planning` | Yes | Reads backlog, allocates tickets to sprints respecting capacity/dependencies |
| `AGENT_TYPE_ESTIMATION` | `estimation` | Yes | Reads historic data, produces estimates with confidence levels |
| `AGENT_TYPE_PRIORITY` | `priority` | Yes | Applies priority rules to tickets |
| `AGENT_TYPE_TEST_AGENT` | `test_agent` | Yes | Writes unit tests from acceptance criteria (ATDD — tests first) |
| `AGENT_TYPE_DEVELOPER` | `developer` | Yes | Writes implementation code to pass tests |
| `AGENT_TYPE_MERGE_AGENT` | `merge_agent` | Yes | Owns the merge queue, merges branches to main |
| `AGENT_TYPE_UI_TEST` | `ui_test` | Yes | Writes/runs Playwright tests (snapshot mode) |
| `AGENT_TYPE_VISUAL_REGRESSION` | `visual_regression` | Yes | Screenshot comparison against baselines |
| `AGENT_TYPE_QUALITY_REVIEW` | `quality_review` | No (standalone) | Reviews merged code for quality |
| `AGENT_TYPE_SECURITY_REVIEW` | `security_review` | No (standalone) | Reviews for security vulnerabilities |
| `AGENT_TYPE_ARCHITECTURE_REVIEW` | `architecture_review` | No (standalone) | Reviews architectural integrity |

### Implementation Touches

Since `agent_type` is a `String(32)` column (not a DB enum), **no migration is needed**. Changes required:

#### Backend

1. **`backend/app/models/agents.py`** — Add new constants:
   ```python
   AGENT_TYPE_PLANNING = "planning"
   AGENT_TYPE_SPRINT_PLANNING = "sprint_planning"
   AGENT_TYPE_ESTIMATION = "estimation"
   AGENT_TYPE_PRIORITY = "priority"
   AGENT_TYPE_TEST_AGENT = "test_agent"
   AGENT_TYPE_DEVELOPER = "developer"
   AGENT_TYPE_MERGE_AGENT = "merge_agent"
   AGENT_TYPE_UI_TEST = "ui_test"
   AGENT_TYPE_VISUAL_REGRESSION = "visual_regression"
   AGENT_TYPE_QUALITY_REVIEW = "quality_review"
   AGENT_TYPE_SECURITY_REVIEW = "security_review"
   AGENT_TYPE_ARCHITECTURE_REVIEW = "architecture_review"
   ```

2. **`backend/app/schemas/agents.py`** — Update `VALID_AGENT_TYPES` frozenset to include all new types. Add a `field_validator` on `agent_type` to actually enforce membership (currently missing — the frozenset is defined but never checked). Update the `AgentBase.agent_type` field description and examples.

3. **`backend/app/schemas/agents.py`** — Update `validate_standalone_board_id` validator. Currently it only enforces "standalone must not have `board_id`" but does **not** enforce that other types **must** have a `board_id`. This needs two-way enforcement:
   - Boardless types (`standalone`, `quality_review`, `security_review`, `architecture_review`) must not have `board_id`
   - All other types **must** have `board_id`

4. **`backend/app/api/agent.py`** — Update `_guard_board_access()` (line ~226): review agent types need the same board-access-grant logic as standalone. Note: `access_level` on board grants is not currently enforced meaningfully — any grant passes access. If read/write semantics matter for review agents, this needs a follow-up. Update `list_self_boards()` (line ~2156): add routing for new boardless types.

   **Existing bug to fix while here:** `list_self_webhooks()` appears to have the wrong response model declared. Fix this while touching the file.

5. **`backend/app/services/openclaw/provisioning_db.py`** — Update `is_gateway_main()` (line ~916): add new boardless review types to the exclusion set. Update `create_agent()` (line ~1646): route review types to standalone-like provisioning.

6. **`backend/app/services/openclaw/provisioning.py`** — Lifecycle manager selection (line ~1275): new board-scoped types can reuse `BoardAgentLifecycleManager`; review types reuse `StandaloneAgentLifecycleManager`.

7. **`backend/app/api/agent_webhooks.py`** — Update the standalone-only guard (line ~116) to allow webhook-capable types (see Feature 2).

8. **`backend/app/api/agent_board_access.py`** — Update the standalone-only guard (line ~48) to allow review types to also have explicit board access grants.

#### Frontend

The frontend has more hard-coded type handling than initially scoped. The full list:

9. **`frontend/src/app/agents/page.tsx`** — Update filter tabs (lines ~54-61): add new categories or use a dynamic approach. Update badge counts (lines ~128-132).

10. **`frontend/src/app/agents/[agentId]/page.tsx`** — Update conditional tab display (lines ~199-272): review types should show Files/Webhooks/Skills/Board-access tabs like standalone agents.

11. **`frontend/src/app/agents/new/page.tsx`** — The creation form is currently a binary `board` vs `standalone` mode, not a general type selector. This needs restructuring to support the full type list — either a type dropdown within each mode, or a single flow where selecting a boardless type removes the board picker.

12. **`frontend/src/components/agents/AgentsTable.tsx`** — Contains hard-coded agent type rendering (badges, icons, labels). Must be updated to display all new types.

13. **`frontend/src/api/standaloneAgents.ts`** — Contains a manual agent type union type. Must be updated to include review types alongside `standalone`, or replaced with the generated type.

14. **`frontend/src/api/generated/`** — After backend schema changes, run `make api-gen` to regenerate the API client. The generated types will pick up the new `VALID_AGENT_TYPES` if the schema exposes them properly.

#### Tests

15. Existing test coverage is thinner than expected. Add or update tests in `backend/tests/` for:
    - Agent creation with each new type (board-scoped and boardless)
    - Validation: new types accepted, unknown types rejected by the new `field_validator`
    - Board-scoped types rejected when `board_id` is missing
    - Boardless types rejected when `board_id` is provided
    - Standalone/review creation routing in `provisioning_db.py`
    - Webhook CRUD for review types (create, list, update, delete)
    - Webhook public ingest for review agent webhooks
    - Board-access CRUD for review types
    - Agent self-endpoints: `/agent/self/webhooks`, `/agent/self/boards`
    - Fix and test `list_self_webhooks()` response model

---

## Feature 2: Webhook-Triggered Standalone Agents

### Purpose

Standalone agents (and the new review agent types) should be activatable via webhooks. The webhook delivery path already exists (`POST /webhooks/agent/{webhook_id}` → Redis queue → dispatch → gateway message), but it's restricted to `AGENT_TYPE_STANDALONE`. This feature widens that to all standalone-like types and improves the activation flow.

### Current Flow (Already Works for `standalone`)

```
External system
  → POST /api/v1/webhooks/agent/{webhook_id}  (unauthenticated, rate-limited)
  → HMAC signature verification (if secret configured)
  → Payload persisted to agent_webhook_payloads table
  → QueuedAgentWebhookDelivery enqueued to Redis
  → RQ worker dequeues
  → dispatch.py builds structured message text
  → Sends to agent's OpenClaw session via gateway API
  → Agent picks up message on next heartbeat/poll cycle
```

### Changes Needed

1. **`backend/app/api/agent_webhooks.py`** — The standalone-only guard is in `_require_standalone_agent()`, called by webhook CRUD endpoints. Change from:
   ```python
   if agent.agent_type != AGENT_TYPE_STANDALONE:
       raise HTTPException(...)
   ```
   to a set-membership check:
   ```python
   WEBHOOK_CAPABLE_TYPES = {
       AGENT_TYPE_STANDALONE,
       AGENT_TYPE_QUALITY_REVIEW,
       AGENT_TYPE_SECURITY_REVIEW,
       AGENT_TYPE_ARCHITECTURE_REVIEW,
   }
   if agent.agent_type not in WEBHOOK_CAPABLE_TYPES:
       raise HTTPException(...)
   ```
   Note: the public ingest path (`POST /webhooks/agent/{webhook_id}`) does **not** check `agent_type` — it only checks for an enabled `AgentWebhook` row. So once a webhook row exists for a review agent, ingest works without further changes.

2. **`backend/app/services/webhooks/dispatch.py`** — No changes needed. The dispatch flow uses `agent_id` to look up the agent and its gateway; it doesn't inspect `agent_type`.

3. **Optional enhancement: Immediate wake on webhook** — Currently delivery uses `deliver=False` (queued for next poll). For time-sensitive webhooks (e.g., CI pipeline completion triggering a review agent), consider adding a `deliver=True` option or a wake endpoint that forces the agent to check in immediately.

4. **Frontend** — Webhook CRUD UI tabs already show for `agent_type === "standalone"`. Update the conditional to also show for review types. This affects `[agentId]/page.tsx` and any type checks in `standaloneAgents.ts`.

5. **Docs/copy cleanup** — Update API error messages and docstrings that still say "standalone-only" in `agent_webhooks.py` and `agent_board_access.py`.

### Use Cases This Enables

- **CI pipeline completes** → webhook fires → Security Review agent wakes and starts review
- **PR opened** → webhook fires → Quality Review agent wakes and starts review
- **Sprint completed** → webhook fires → Architecture Review agent wakes and starts review
- **External tool reports results** → webhook fires → relevant agent processes the data

---

## Hardware & Model Infrastructure

Three machines pooled via LM Studio Link:

| Machine | RAM | Models Loaded |
|---|---|---|
| Main Mac (workstation) | 16GB | Qwen3.5 9B (context: 8192) |
| Mac Mini (dedicated server) | 16GB | Ministral 3 14B Reasoning (context: 16384) |
| Work Machine (dedicated server) | 24GB | Devstral Small 2 (context: 16384), Granite 4 Tiny (context: 4096) |

All models accessible via LM Studio Link at `http://localhost:1234/v1`.

**Paid providers:**
- GitHub Copilot (OAuth via `gh` CLI): Claude Sonnet 4.6, Claude Opus 4.6, GPT-5.4
- ZAI/GLM (API key, when subscribed): GLM 5.1

---

## Agent Roster

### Core Workflow Agents (Free — Local Models)

**Board Lead**
- Type: `board_lead`
- Model: `lmstudio/qwen/qwen3.5-9b`
- Role: Sole entry point. Orchestrates all other agents. Assigns tickets. Monitors sprint board. Synthesises reports. Triggers review gates when all tickets are Done. Never performs coding, testing, or planning work itself.
- Trigger for review gate: All tickets in current sprint have status `done`.
- Trigger for next sprint: All review gates pass.

**Planning Agent**
- Type: `planning` (NEW)
- Model: `lmstudio/mistralai/ministral-3-14b-reasoning`
- Role: Works interactively with the user to define features. Breaks plans into tickets with acceptance criteria. Tickets are the input contract for all downstream agents.

**Sprint Planning Agent**
- Type: `sprint_planning` (NEW)
- Model: `lmstudio/mistralai/ministral-3-14b-reasoning`
- Role: Reads backlog with estimates and priorities. Reads sprint capacity from `~/.openclaw/data/sprint-capacity.md` (or board memory). Allocates tickets to sprints respecting capacity, dependencies, feature delivery objectives, and priority. Each sprint must deliver testable, independently deployable units. Outputs sprint plan with rationale for any deferrals.

**Estimation Agent**
- Type: `estimation` (NEW)
- Model: `lmstudio/mistralai/ministral-3-14b-reasoning`
- Role: Reads historic estimate vs actual data from `~/.openclaw/data/estimates-history.csv` (or board memory). Identifies comparable historic tickets. Applies historic ratio to produce estimates. Output: story points, hours, confidence level, and the specific historic data used. Never estimates without reading historic data first.

**Priority Agent**
- Type: `priority` (NEW)
- Model: `lmstudio/ibm/granite-4-h-tiny`
- Role: Reads priority rules from `~/.openclaw/data/priority-rules.md` (or board memory). Applies rules literally to each ticket. Output: Critical / High / Medium / Low plus `priority_score` (1-100) with one-line justification. Does not interpret or override priority rules.

**Test Agent**
- Type: `test_agent` (NEW)
- Model: `lmstudio/mistralai/devstral-small-2-2512`
- Role: Receives a ticket with acceptance criteria. Writes unit tests **before any implementation code is written**. This is the ATDD discipline — tests first, implementation second. Hands unit tests to Developer Agent.

**Developer Agent**
- Type: `developer` (NEW)
- Model: `lmstudio/mistralai/devstral-small-2-2512`
- Role: Receives a ticket with unit tests already written. Writes implementation code to pass the unit tests. Commits when all unit tests pass locally. Hands work to Merge Agent.

**Merge Agent**
- Type: `merge_agent` (NEW)
- Model: `lmstudio/mistralai/devstral-small-2-2512`
- Role: Owns the merge queue. Merges completed branches to main in queue order. Resolves merge conflicts where possible using code understanding. Escalates unresolvable conflicts to the Developer Agent that owns the conflicting code. When all sprint tickets are merged to main, triggers push to remote to initiate UI testing and review gates. Each board has its own Merge Agent instance.

**UI Test Agent**
- Type: `ui_test` (NEW)
- Model: `lmstudio/mistralai/devstral-small-2-2512`
- Role: Writes and executes Playwright tests using snapshot mode (accessibility tree, not screenshots). Tests are written once per feature and re-run each sprint. Operates post-merge to main. Long user journeys are segmented — each agent handles a logical section and passes state to the next segment.

**Visual Regression Agent**
- Type: `visual_regression` (NEW)
- Model: Vision model (Qwen3 VL 4B, hot-swapped onto work machine via TTL when Devstral is idle)
- Role: Captures and compares UI screenshots against baselines. Operates post-merge to main. Reports visual diffs. Raises tickets for genuine regressions. Does not raise tickets for expected changes.

### Review Gate Agents (Paid)

Review agents are triggered by the Board Lead only when all sprint tickets are Done. They produce tickets for remediation work, which are added to the current sprint. The sprint does not close until all review gates pass. Review agents are **webhook-capable** — they can be triggered by CI pipeline events or other external systems.

**Quality Review Agent**
- Type: `quality_review` (NEW — boardless, webhook-capable)
- Model: `github-copilot/claude-sonnet-4-6`
- Role: Reviews merged code for quality, maintainability, test coverage, and adherence to standards. Raises tickets for issues found. Does not fix issues itself.

**Security Review Agent**
- Type: `security_review` (NEW — boardless, webhook-capable)
- Model: `github-copilot/claude-opus-4-6`
- Role: Reviews merged code for security vulnerabilities, insecure patterns, dependency risks. Raises tickets for all findings. Does not fix issues itself. Highest priority findings block sprint closure.

**Architecture Review Agent**
- Type: `architecture_review` (NEW — boardless, webhook-capable)
- Model: `github-copilot/claude-opus-4-6`
- Role: Reviews merged code for architectural integrity, design patterns, technical debt, and alignment with system design. Raises tickets for structural concerns. Does not fix issues itself.

### Circuit Breaker Agents

Activated when a Developer Agent is stuck on a ticket after a defined number of failed attempts (default: 3 attempts with the same blocker).

**GLM Senior Developer**
- Type: `standalone` (existing type)
- Model: `zai/glm-5.1`
- Role: Senior developer consulted when Developer Agent cannot resolve a blocker. Reviews the problem, provides a solution approach or direct fix. If unresolved after one attempt, escalates to Opus Senior Developer.

**Opus Senior Developer**
- Type: `standalone` (existing type)
- Model: `github-copilot/claude-opus-4-6`
- Role: Last automated resort before human escalation. Receives full context of the blocker including all previous attempts. If unresolved after one attempt, escalates to the human via Board Lead.

---

## Sprint Workflow

The workflow uses Mission Control's existing sprint and task primitives. Agents interact with the target project's repository (not the Mission Control codebase) through the bash tool and git.

```
User → Planning Agent
         ↓ Creates tickets with acceptance criteria
       Sprint Planning Agent
         ↓ Allocates tickets to sprint (uses Mission Control sprint API)
       Estimation Agent + Priority Agent (per ticket)
         ↓ Sets estimate_minutes and priority_score on each task
       For each ticket in sprint:
         Test Agent → writes unit tests from acceptance criteria
         Developer Agent → writes code to pass unit tests
         Merge Agent → queues and merges to main
         ↓
       All tickets Done?
         ↓ YES
       Push to remote
         ↓
       UI Test Agent (Playwright, snapshot mode)
       Visual Regression Agent
         ↓
       Review Gates:
         Quality Review Agent (triggered via webhook from CI or by Board Lead)
         Security Review Agent (triggered via webhook from CI or by Board Lead)
         Architecture Review Agent (triggered via webhook from CI or by Board Lead)
         ↓
       All reviews pass?
         ↓ YES → Sprint completed → Load next sprint
         ↓ NO  → Remediation tickets added to current sprint → loop
```

**Stuck ticket circuit breaker:**
```
Developer Agent stuck (3 attempts)
  → GLM Senior Developer (standalone, activated by Board Lead assigning task)
      → Still stuck: Opus Senior Developer
          → Still stuck: Escalate to human via Board Lead (ask-user endpoint)
```



---

## Model Configuration

### Gateway `openclaw.json`

This is the OpenClaw runtime configuration on each gateway machine. The `models.providers` block matches the actual `ModelDefinitionConfig` type from `src/config/types.models.ts`:

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "lmstudio": {
        "baseUrl": "http://localhost:1234/v1",
        "api": "openai-responses",
        "apiKey": "lm-studio",
        "models": [
          {
            "id": "qwen/qwen3.5-9b",
            "name": "Qwen 3.5 9B",
            "contextWindow": 8192,
            "maxTokens": 4096,
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "reasoning": true,
            "input": ["text"]
          },
          {
            "id": "mistralai/ministral-3-14b-reasoning",
            "name": "Ministral 14B Reasoning",
            "contextWindow": 16384,
            "maxTokens": 8192,
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "reasoning": true,
            "input": ["text"]
          },
          {
            "id": "mistralai/devstral-small-2-2512",
            "name": "Devstral Small 2",
            "contextWindow": 16384,
            "maxTokens": 8192,
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "reasoning": false,
            "input": ["text"]
          },
          {
            "id": "ibm/granite-4-h-tiny",
            "name": "Granite 4 Tiny",
            "contextWindow": 4096,
            "maxTokens": 2048,
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "reasoning": false,
            "input": ["text"]
          }
        ]
      }
    }
  },

  "agents": {
    "list": [
      {
        "id": "board-lead",
        "model": { "primary": "lmstudio/qwen/qwen3.5-9b" }
      },
      {
        "id": "planning",
        "model": { "primary": "lmstudio/mistralai/ministral-3-14b-reasoning" }
      },
      {
        "id": "sprint-planning",
        "model": { "primary": "lmstudio/mistralai/ministral-3-14b-reasoning" }
      },
      {
        "id": "estimation",
        "model": { "primary": "lmstudio/mistralai/ministral-3-14b-reasoning" }
      },
      {
        "id": "priority",
        "model": { "primary": "lmstudio/ibm/granite-4-h-tiny" }
      },
      {
        "id": "test-agent",
        "model": { "primary": "lmstudio/mistralai/devstral-small-2-2512" }
      },
      {
        "id": "developer",
        "model": { "primary": "lmstudio/mistralai/devstral-small-2-2512" }
      },
      {
        "id": "merge-agent",
        "model": { "primary": "lmstudio/mistralai/devstral-small-2-2512" }
      },
      {
        "id": "ui-test-agent",
        "model": { "primary": "lmstudio/mistralai/devstral-small-2-2512" }
      },
      {
        "id": "visual-regression-agent",
        "model": { "primary": "lmstudio/qwen/qwen3-vl-4b" }
      }
    ]
  },

  "bindings": [
    { "agentId": "board-lead", "match": { "channel": "default" } }
  ]
}
```

### Mission Control Agent Records

Agents are created via the Mission Control API. Each agent specifies its new type:

```bash
# Planning Agent (board-scoped, new type)
curl -X POST "${MC_BASE_URL}/api/v1/agents" \
  -H "Authorization: Bearer ${MC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Planning Agent",
    "board_id": "<board-uuid>",
    "gateway_id": "<gateway-uuid>",
    "agent_type": "planning",
    "heartbeat_config": {"every": "10m", "target": "last", "includeReasoning": false},
    "identity_profile": {
      "name": "Planning Agent",
      "emoji": "📋"
    }
  }'

# Security Review Agent (boardless, webhook-capable, new type)
curl -X POST "${MC_BASE_URL}/api/v1/agents" \
  -H "Authorization: Bearer ${MC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Security Review Agent",
    "gateway_id": "<gateway-uuid>",
    "agent_type": "security_review",
    "heartbeat_config": {"every": "30m", "target": "last", "includeReasoning": false},
    "identity_profile": {
      "name": "Security Reviewer",
      "emoji": "🔒"
    }
  }'
```

After creating review agents, configure webhooks so they can be triggered by external events:

```bash
# Create webhook for Security Review Agent
curl -X POST "${MC_BASE_URL}/api/v1/agents/<security-review-agent-id>/webhooks" \
  -H "Authorization: Bearer ${MC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "CI pipeline completion trigger",
    "enabled": true,
    "secret": "<hmac-secret>"
  }'

# External CI can then POST to:
# POST /api/v1/webhooks/agent/<webhook-id>
# with HMAC signature in the configured header
```

---

## Cost Strategy

**Free (local models):** Planning, sprint planning, estimation, priority, test writing, development, merging, UI testing — the entire development loop runs at zero cost.

**Paid (GitHub Copilot):** Quality review, security review, architecture review, GLM senior dev (if subscribed), Opus senior dev, circuit breaker escalation. Paid models activate only at sprint end review gates and on stuck ticket escalation.

**Cost controls:**
- Board Lead must confirm with user before triggering security or architecture review (Opus) if the sprint had no significant structural changes.
- Circuit breaker escalation to Opus requires Board Lead to log the reason and notify the user.
- GLM 5.1 acts as the cost buffer between free agents and expensive Opus calls.

---

## Data Files Required

Create these before running the system. They can live as files on the filesystem or as board memory entries in Mission Control:

### Filesystem Option
```
~/.openclaw/data/
  estimates-history.csv     ← historic ticket estimate vs actual (required for Estimation Agent)
  priority-rules.md         ← priority framework document (required for Priority Agent)
  sprint-capacity.md        ← team velocity and sprint capacity (required for Sprint Planning Agent)
```

### Board Memory Option

Store as board memory entries tagged for each consuming agent. Agents read via `GET /api/v1/agent/boards/{id}/memory?tags=priority-rules`.

---

## Still To Be Configured

The following are planned but not yet implemented:

- **rembr.ai** — RAG integration for token reduction. Will reduce context sent to agents by retrieving only relevant information rather than full documents.
- **Rust token killer skill** — compresses token usage in agent processing.
- **Text-speak skill** — truncates agent-to-agent communication to reduce inter-agent token costs. Apply after RAG and token killer to maximise savings.
- **Agent SOUL files** — detailed persona and constraint files for each agent workspace. These are defined via `soul_template` on the Agent record or `BoardTemplate` overrides. Need to be written for each of the new agent types.
- **Pen testing integration** — separate automated process, not yet defined.
- **Skills to create:**
  - `code-review-checklist` — structured review process for review agents
  - `estimation-methodology` — historic data lookup and ratio-based estimation

---

## Implementation Sequence

Recommended order for building the platform features:

### Phase 1: New Agent Types (backend)
1. Add constants to `backend/app/models/agents.py`
2. Update `VALID_AGENT_TYPES` and add field validator in `backend/app/schemas/agents.py`
3. Update standalone board_id validation for boardless review types
4. Update `_guard_board_access()` and `list_self_boards()` in `backend/app/api/agent.py`
5. Update provisioning routing in `backend/app/services/openclaw/provisioning_db.py`
6. Update lifecycle manager selection in `backend/app/services/openclaw/provisioning.py`
7. Update `is_gateway_main()` exclusion set
8. Write tests

### Phase 2: Webhook-Triggered Standalone Agents (backend)
1. Update webhook guard in `backend/app/api/agent_webhooks.py`
2. Update board-access guard in `backend/app/api/agent_board_access.py`
3. Write tests

### Phase 3: Frontend Updates
1. Run `make api-gen` to regenerate the API client
2. Update `standaloneAgents.ts` type union
3. Update `AgentsTable.tsx` type rendering
4. Update agent list page (`page.tsx`) filters and badges
5. Update agent detail page (`[agentId]/page.tsx`) conditional tabs
6. Restructure agent creation form (`new/page.tsx`) from binary board/standalone to full type support

### Phase 4: Skills & Templates
1. Write SOUL.md templates for each new agent type
2. Create skills: `code-review-checklist`, `estimation-methodology`
3. Write HEARTBEAT.md template overrides for specialised agent operational loops

### Phase 5: Workflow Configuration
1. Create gateway, board group, boards in Mission Control
2. Create agents with correct types
3. Configure webhooks for review agents
4. Create data files (estimates history, priority rules, sprint capacity)
5. Run initial sprint

---

*Document version: April 2026. Implementation plan for the agentic development system, built on OpenClaw and Mission Control.*
