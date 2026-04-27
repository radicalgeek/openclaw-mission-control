# AxiaCraft Product Foundry — Architecture

## High level

AxiaCraft Product Foundry is a full-stack web application that provides centralized operations and governance for running AI agent teams. It combines work orchestration (kanban boards, sprints, planning), team communication (channels), agent lifecycle management, and approval-driven governance into a single platform.

- **Frontend**: Next.js 16 (React 19, TypeScript, Tailwind CSS)
- **Backend**: FastAPI (Python, SQLModel, Alembic, async SQLAlchemy)
- **Database**: PostgreSQL 16
- **Cache / Queue**: Redis 7 (RQ background workers, rate limiting)
- **Authentication**: Clerk JWT or shared bearer token (local mode)
- **Deployment**: Docker Compose (5 services: db, redis, backend, frontend, webhook-worker)

## System architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Developer / Operator                  │
│                    (Web Browser / UI)                       │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (Next.js)                      │
│  ┌─────────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │  Pages      │ │  React   │ │  TanStack│ │  Recharts  │  │
│  │  (RSC)      │ │  +Radix  │ │  Query   │ │  Charts    │  │
│  └─────────────┘ └──────────┘ └──────────┘ └────────────┘  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  API Client (orval-generated) + TanStack Query           │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     Backend (FastAPI)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐ │
│  │  Auth    │ │  RBAC    │ │  CRUD    │ │  Business      │ │
│  │  (Clerk/ │ │  /       │ │  /       │ │  Services      │ │
│  │  Local)  │ │  Policy  │ │  Routes  │ │  (lifecycle,   │ │
│  └──────────┘ └──────────┘ └──────────┘ │  webhooks,      │ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ │  telemetry,     │ │
│  │  Agent   │ │  Queue   │ │  Webhook │ │  governance)    │ │
│  │  Auth    │ │  Worker  │ │  Engine  │ │                │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  SQLModel ORM + Alembic Migrations                      │ │
│  └──────────────────────────┬──────────────────────────────┘ │
└─────────────────────────────┼─────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
      ┌───────────────┐              ┌───────────────┐
      │  PostgreSQL 16 │              │     Redis 7    │
      │  (Product      │              │  (RQ Queue,    │
      │   Foundry)     │              │   Rate Limit)  │
      └───────────────┘              └───────────────┘
```

## Service breakdown

### 1. Frontend (Next.js)

**Location**: `frontend/`

**Stack**:
- Next.js 16.1 (App Router, React 19)
- TypeScript 5, ESLint, Prettier
- Tailwind CSS 3 + Radix UI primitives
- TanStack Query v5 (data fetching + caching)
- TanStack Table v8 (data tables)
- Recharts 3 (charts / burndown)
- Vitest + Testing Library (unit tests)
- Cypress 14 (E2E tests)
- Orval (OpenAPI codegen for API client)

**Key directories**:
- `src/app/` — Next.js App Router pages (dashboard, boards, sprints, channels, planning, agents, gateways, skills, organization, settings, onboarding)
- `src/components/` — React components organized by domain (boards, agents, sprints, channels, etc.) and by pattern (atoms, molecules, organisms)
- `src/lib/` — Shared utilities (API base client, branding, datetime, formatters, onboarding helpers)
- `src/api/generated/` — Auto-generated API client from OpenAPI spec
- `cypress/` — Cypress E2E tests

**State management**: TanStack Query for server-state; React context for auth, query provider, branding.

**Routing**: App Router with nested layouts. Root layout wraps everything with `AuthProvider`, `QueryProvider`, `BrandingProvider`.

### 2. Backend (FastAPI)

**Location**: `backend/`

**Stack**:
- Python 3.12+, FastAPI
- SQLModel (ORM, Pydantic-based)
- SQLAlchemy 2.x (async)
- Alembic (migrations)
- RQ (Redis Queue) for background workers
- Pydantic Settings (env-based config)
- pytest (tests)

**Key directories**:
- `app/api/` — 36+ route modules covering all REST endpoints
- `app/models/` — 30+ SQLModel data models
- `app/schemas/` — Pydantic request/response schemas
- `app/services/` — Business logic (lifecycle, webhooks, telemetry, queue, mentions, planning, etc.)
- `app/core/` — Config, auth, security headers, logging, rate limiting, error handling
- `app/db/` — Session management, query manager, CRUD helpers
- `app/webhooks/` — Webhook classifier
- `migrations/` — Alembic migration revisions
- `templates/` — Jinja2 templates for gateway agent boards
- `scripts/` — CLI scripts (migration graph check, OpenAPI export, seed demo, template sync)

**API structure**: All routes under `/api/v1/` prefix. Health endpoints at `/health`, `/healthz`, `/readyz`.

### 3. Database (PostgreSQL)

**Schema**: 30+ tables covering the full domain model.

**Core tables**:
- `organizations` — Top-level tenant
- `board_groups` — Groupings of boards
- `boards` — Workspaces with goals, tasks, agents
- `tasks` — Work items with status, assignment, sprint membership
- `sprints` / `sprint_tickets` — Time-boxed delivery cycles
- `agents` — AI agent configurations, tokens, lifecycle state
- `gateways` — External OpenClaw runtime connections
- `approvals` — Human-in-the-loop approval requests
- `channels` / `threads` / `thread_messages` — Messaging system
- `plans` — Markdown planning documents with agent chat
- `tags` / `tag_assignments` — Cross-cutting labels
- `usage_snapshots` — Token/cost tracking
- `audit_log` — Agent audit trail
- `board_templates` / `board_onboarding` — Template and onboarding state

**Tenancy**: Most tables include `organization_id` or `board_id` for multi-tenant isolation. The `TenantScoped` base class enforces this.

### 4. Background Workers (RQ + Redis)

**Service**: `webhook-worker` in Docker Compose

**Queue types**:
- **Lifecycle reconciliation** — Agent lifecycle state reconciliation with OpenClaw gateways
- **Webhook dispatch** — Outbound webhook delivery with retry and exponential backoff
- **Usage polling** — Agent token/cost usage data collection

**Mechanics**:
- Tasks are JSON envelopes with `task_type`, `payload`, `created_at`, `attempts`
- Scheduled delivery via Redis sorted sets (delayed tasks)
- Exponential backoff with jitter on failures
- Max retries configurable (`RQ_DISPATCH_MAX_RETRIES`, default 3)
- Worker runs in a continuous async loop with configurable throttle

## Authentication & Authorization

### Two modes (configurable via `AUTH_MODE`):

1. **Local mode** (`AUTH_MODE=local`): Shared bearer token (`LOCAL_AUTH_TOKEN`, min 50 chars). Simple, suitable for self-hosted/internal use.

2. **Clerk mode** (`AUTH_MODE=clerk`): Clerk JWT authentication. Full user identity, roles, and session management via Clerk.

### Agent authentication:

Separate from user auth. Agents authenticate via `X-Agent-Token` header (or `Authorization: Bearer`). Uses:
- PBKDF2-hashed tokens stored in DB
- Fast-path SHA-256 indexed lookup (`agent_token_fast_hash`)
- Legacy fallback for older agents
- Rate limiting per client IP
- Best-effort `last_seen_at` updates (throttled to 30s intervals)

### Authorization model:

- **User auth**: Clerk JWT claims or local token → user identity
- **Agent auth**: `X-Agent-Token` → Agent record → board access policies
- **Board access**: `AgentBoardAccess` and `OrganizationBoardAccess` models define what agents/users can do on which boards
- **Governance**: `GovernancePolicy` enforces budget controls, role capabilities, and approval requirements

## Key data flows

### Task lifecycle

```
User creates task → Board service → Task model (status: inbox)
    → Agent picks up task → Status: in_progress
    → Agent completes task → Status: done
    → If require_approval → Approval request created
    → Human reviews → Approval resolved → Task status: done
```

### Agent provisioning

```
User creates agent → Agent model (status: provisioning)
    → Lifecycle queue task enqueued
    → Worker reconciles with OpenClaw gateway
    → Gateway provisions runtime → Agent status: online
    → Agent token minted → Stored (hashed) in DB
```

### Gateway integration

```
Gateway configured → Gateway model (URL, token)
    → Boards can be linked to gateways
    → Agents assigned to gateways
    → WebSocket protocol for real-time communication
    → MCP proxy for tool discovery and execution
```

### Approval flow

```
Task action triggers approval → Approval model (status: pending)
    → Confidence score + rubric scores stored
    → Human reviews → Status: approved/rejected
    → Board lifecycle service enforces approval gates
```

## Deployment

### Docker Compose (5 services):

```yaml
services:
  db:              # PostgreSQL 16
  redis:           # Redis 7
  backend:         # FastAPI (port 8000)
  frontend:        # Next.js (port 3000)
  webhook-worker:   # RQ worker (no ports)
```

### Build & deploy:

- `make setup` — Install deps
- `make check` — CI parity (lint, typecheck, test, coverage, build)
- `docker compose up -d --build` — Full stack
- `make docker-up` — Docker Compose up with rebuild
- Cross-platform builds: `docker buildx build --platform linux/amd64,linux/arm64 --push`

### CI/CD:

- ArgoCD manifests in `deploy/argocd/`
- K8s manifests in `deploy/k8s/`
- Docker images in `deploy/docker/`

## Testing strategy

### Backend (pytest):
- Unit tests in `backend/tests/`
- Coverage policy: 100% on scoped modules (`app.core.error_handling`, `app.services.mentions`)
- `make backend-test` — Run tests
- `make backend-coverage` — Coverage gate

### Frontend (Vitest):
- Unit tests co-located with source files (`.test.ts` / `.test.tsx`)
- Testing Library for component tests
- `make frontend-test` — Run tests
- `make frontend-test:full-coverage` — Full coverage mode

### E2E (Cypress):
- Tests in `frontend/cypress/`
- Requires running stack
- `npm run e2e` — Run E2E suite

### Migration testing:
- `make backend-migration-check` — Validates migration graph + reversible path on clean Postgres

## Security

- **Security headers**: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
- **CORS**: Configurable origins via `CORS_ORIGINS`
- **Rate limiting**: Memory or Redis backend, configurable
- **Trusted proxies**: CIDR support for X-Forwarded-For extraction
- **Webhook payload limit**: 1 MB max
- **Secrets**: Never committed; `.env.example` has placeholders only
- **Vulnerability reporting**: GitHub Security Advisories (private)

## Domain model overview

```
Organization
  ├── BoardGroup (optional grouping)
  │   └── Board
  │       ├── Tasks (with Sprint membership)
  │       │   ├── Dependencies
  │       │   ├── Custom Fields
  │       │   ├── Tags
  │       │   ├── Approvals
  │       │   └── Thread (channel conversation)
  │       ├── Agents (assigned to board)
  │       ├── Channels (messaging)
  │       │   └── Threads → ThreadMessages
  │       ├── Plans (markdown docs)
  │       ├── Sprints (time-boxed cycles)
  │       ├── Webhooks (outbound)
  │       ├── Memory (persistent context)
  │       └── Onboarding state
  ├── Gateways (external runtimes)
  ├── Skills Marketplace
  ├── Souls Directory
  └── Governance Policies
```

## Configuration

### Environment variables (`.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTH_MODE` | `local` or `clerk` | (required) |
| `LOCAL_AUTH_TOKEN` | Shared token (min 50 chars) | (required for local) |
| `CLERK_SECRET_KEY` | Clerk JWT secret | (required for clerk) |
| `DATABASE_URL` | PostgreSQL connection string | (required) |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:3000` |
| `BASE_URL` | Public backend URL | `http://localhost:8000` |
| `DB_AUTO_MIGRATE` | Run Alembic on startup | `true` (dev) |
| `RATE_LIMIT_BACKEND` | `memory` or `redis` | `memory` |
| `CHANNELS_ENABLED` | Enable channels feature | `false` |
| `PLANNING_ENABLED` | Enable planning feature | `true` |

### Feature flags:

- `CHANNELS_ENABLED` — Toggle channel messaging
- `PLANNING_ENABLED` — Toggle planning documents

## Notable design decisions

1. **SQLModel over pure SQLAlchemy**: Combines Pydantic + SQLAlchemy for concise, type-safe models. Reduces boilerplate but limits some advanced SQLAlchemy features.

2. **Async-first**: All DB operations use async SQLAlchemy. No sync code paths.

3. **Agent auth separate from user auth**: Allows independent evolution of agent policy (tokens, rate limits, board access) without affecting user auth.

4. **Fast hash for agent tokens**: SHA-256 indexed lookup avoids full-table PBKDF2 scans. Legacy agents auto-migrate to fast path.

5. **RQ over Celery**: Simpler queue system, fewer moving parts. Suitable for self-hosted deployments.

6. **Orval for API client**: OpenAPI-first codegen ensures frontend API client stays in sync with backend. No manual API client maintenance.

7. **Template-based board generation**: Jinja2 templates (`templates/`) generate board content for gateway agents. Synced via `sync_gateway_templates.py`.

8. **Multi-tenant by design**: `TenantScoped` base class enforces organization-level scoping on most models.

## Documentation structure

```
docs/
├── architecture/     # This document
├── development/      # Contributor workflow
├── testing/          # Test guide
├── deployment/       # Production deployment
├── operations/       # Runbooks, monitoring
├── policy/           # Governance, security
├── production/       # Production hardening
├── reference/        # API reference, schemas
├── release/          # Release checklist
├── troubleshooting/  # Debugging guides
├── getting-started/  # Onboarding
├── channels.md       # Channel messaging deep-dive
├── openclaw_gateway_ws.md  # Gateway WebSocket protocol
├── standalone-agents-implementation.md  # Agent architecture
├── style-guide.md    # Design system
├── installer-support.md  # Installer compatibility
└── screenshots/      # UI screenshots
```
