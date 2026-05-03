# Codebase Analysis: openclaw-mission-control

> Generated: 2026-04-28

---

## 1. Project Overview

This is an **AI agent operations platform** (rebranded as "AxiaCraft Product Foundry") that manages AI agents, boards, sprints, tasks, and MCP (Model Context Protocol) integrations. It follows a full-stack architecture with a Python/FastAPI backend and a Next.js frontend.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16.1, React 19, TypeScript 5, Tailwind CSS 3, Radix UI, TanStack Query v5 |
| Backend | Python 3.12+, FastAPI, SQLModel, async SQLAlchemy 2.x, Alembic, RQ |
| Database | PostgreSQL 16 |
| Cache/Queue | Redis 7 (RQ workers, rate limiting) |
| Auth | Clerk JWT or shared bearer token (local mode) |
| Deployment | Docker Compose (5 services), Docker Hub, ArgoCD |
| Testing | pytest, Vitest + Testing Library, Cypress (E2E) |

### Structure

```
openclaw-mission-control/
  backend/          # FastAPI service (app/, migrations/, templates/, tests/)
  frontend/         # Next.js app (src/app/, src/components/, cypress/)
  docs/             # Architecture, deployment, operations guides
  compose.yml       # Docker Compose (db, redis, backend, frontend, webhook-worker)
```

---

## 2. Recent Changes (Last 50 Commits)

### April 2026

| Date | Focus | Highlights |
|------|-------|------------|
| Apr 27 | Docker | Dynamic env var injection, entrypoint script |
| Apr 21 | **Telemetry** | Governance and MCP proxy support (major feature) |
| Apr 19 | Platform | AxiaCraft platform updates |
| Apr 4 | Charts | Agent chart rendering via `json:chart` blocks |
| Apr 3 | **Agent files** | File viewer/editor, board template editor (Phases 1–3) |
| Apr 3 | Sprints | Backlog shows inbox-only by default |
| Apr 3 | Planning | Markdown preview rendering fix |
| Apr 3 | Nav | Sidebar restructured into Overview/Projects/Agents/Administration |
| Apr 3 | Brand | Rebrand to AxiaCraft Product Foundry (multiple commits) |
| Apr 2 | Theme | Dark-mode CSS overrides, gradient removal (11 commits) |
| Mar 30 | Sprints | Drag-reorder, backlog detail panel, board selector, rich ticket fields |
| Mar 30 | Planning | Route messages to board lead session, auto-poll on load |
| Mar 30 | Deploy | Docker Hub migration, k8s fixes, NEXT_PUBLIC_API_URL fixes |

**Trend**: Heavy focus on rebranding, dark-mode fixes, sprint management, planning documents, and telemetry governance.

---

## 3. Incomplete Features (Added Recently)

### 3.1 Deferred Telemetry Governance Phases (Phase 4–6)

Planned but **not yet implemented** per `TELEMETRY_IMPLEMENTATION_REPORT.md`:

| Feature | Phase | Status |
|---------|-------|--------|
| Real-time gateway event subscription (WebSocket) | 4 | Deferred |
| Budget auto-pause enforcement (`budget_paused` agent status) | 4 | Deferred |
| Model allow-list enforcement at provision time | 6 | Deferred |
| Skill deny-list enforcement at install time | 6 | Deferred |
| Session TTL scheduled compaction job | 6 | Deferred |
| Audit log retention pruning job | 5 | Deferred |
| PII redaction filter on `agent_audit_log.detail` | 5 | Deferred |
| SSE live audit trail endpoint | 4 | Deferred |

### 3.2 Deferred Items from Agentic Development Plan

| Feature | Description |
|---------|-------------|
| rembr.ai | RAG integration for token reduction |
| Rust token killer skill | Compresses token usage |
| Text-speak skill | Truncates inter-agent communication |
| Agent SOUL files | Persona/constraint files for new agent types (need writing) |
| Pen testing integration | Not yet defined |
| `code-review-checklist` skill | Listed in plan but not created |

### 3.3 Deferred MCP Gateway Protocol

Phase 2B (full MCP gateway protocol extension) is **planned but not implemented** — only Phase 2A (built-in charts) shipped.

### 3.4 Queue Worker Gap

Per `TELEMETRY_GOVERNANCE_PLAN.validated.md`: "The queue layer already supports additional payload types, but not every defined queue task is wired into the generic worker loop yet."

---

## 4. Known Issues & Risks

### 4.1 DoS Risk: O(N) Agent Token Verification

- **File**: `backend/tests/test_agent_auth_token_lookup_regression.py`
- **Issue**: `_find_agent_for_token` performs PBKDF2 verification in a loop over ALL agents. Each verify costs ~200k iterations. Marked `xfail` to document the desired O(1) fix.
- **Impact**: Potential denial-of-service as agent count grows.

### 4.2 `VALID_AGENT_TYPES` Not Enforced

- **File**: `AGENTIC_DEV_PLAN.md` line 46 / `backend/app/schemas/agents.py`
- **Issue**: The `VALID_AGENT_TYPES` frozenset is defined but no `field_validator` exists. Any string is accepted.
- **Impact**: Invalid agent types can be created at runtime.

### 4.3 Organization `settings` Stored as JSON, Not JSONB

- **File**: `TELEMETRY_IMPLEMENTATION_REPORT.md` line 47
- **Issue**: Migration adds `settings` as `sa.JSON()` instead of `sa.JSONB()`, missing query optimization opportunities.

### 4.4 No Audit Trail for Governance Setting Changes

- **File**: `TELEMETRY_GOVERNANCE_PLAN.validated.md` line 56
- **Issue**: Board update code computes `changed_fields`, but governance-flag changes are not explicitly emitted to the activity stream.

### 4.5 Migration `t0a1b2c3d4e5` Is a No-Op Chain

- **File**: `backend/migrations/versions/t0a1b2c3d4e5_merge_heads_for_telemetry.py`
- Both `upgrade()` and `downgrade()` are empty `pass` statements (intentional, just chains revisions).

---

## 5. Architecture Observations

### Strengths

- **Clean separation of concerns**: API routes, models, schemas, services, core infrastructure well-organized
- **Comprehensive agent lifecycle management**: Board workers, board leads, gateway main, standalone agents with full provisioning/deletion
- **Robust template override cascade**: per-agent → per-board → org-wide → built-in `.j2` files
- **Good migration practices**: All 47 migrations are idempotent, properly chained, with downgrade support
- **Multi-org support with RBAC**: Three-tier roles (member/admin/owner) with per-project board access scoping
- **Extensive activity logging**: 35+ event types covering agent lifecycle, tasks, sprints, planning, approvals, file operations
- **Webhook infrastructure**: Inbound (GitHub Actions, PRs, deployments) and outbound (board/agent/sprint) with retry

### Areas of Active Development

- **MCP Apps**: Phase 2A (charts) shipped; Phase 2B (full protocol extension) planned
- **Telemetry governance**: Phases 1–3 (backend) shipped; Phases 4–6 (enforcement, UI, compliance) deferred
- **Sprint management**: Recently enhanced with drag-reorder, backlog detail panel, board selector
- **Planning documents**: Recently added markdown-based planning with agent chat integration

---

## 6. Code Quality Indicators

| Metric | Finding |
|--------|---------|
| TODO/FIXME/HACK/XXX markers | **Zero** found in source code |
| Commented-out code | None found |
| Disabled routes | None found — all 37+ routers active |
| Skipped tests | None in backend or frontend suites |
| Migration completeness | All 47 migrations properly chained, idempotent |
| Test coverage | pytest (backend), Vitest (frontend), Cypress (E2E) |

---

## 7. Summary

This is a mature, well-structured AI agent operations platform. The codebase is notably clean — zero TODO/FIXME markers in source, all routes active, migrations complete.

### Key Findings

1. **Deferred governance features** (Phases 4–6) represent the largest set of incomplete features: budget enforcement, model/skill allow-lists, session compaction, audit retention, PII redaction
2. **Performance risk**: O(N) agent token verification is documented as `xfail` and needs O(1) refactor
3. **Validation gaps**: `VALID_AGENT_TYPES` is defined but not enforced at schema level
4. **Template debt**: Agent SOUL files need to be written for all new agent types per the agentic development plan
5. **Queue wiring incomplete**: Not all defined queue tasks are connected to the generic worker loop

### Priority Recommendations

| Priority | Action |
|----------|--------|
| High | O(1) agent token verification refactor (DoS risk) |
| High | Enforce `VALID_AGENT_TYPES` at schema level |
| Medium | Complete telemetry governance Phases 4–6 |
| Medium | Wire remaining queue tasks to worker loop |
| Low | Write Agent SOUL files for new agent types |
| Low | Add PII redaction filter on audit logs |
