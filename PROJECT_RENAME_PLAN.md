# Boards → Projects: Concept Separation Plan

> **Status**: Draft (rev 2)  
> **Date**: 2026-04-19 (rev 1: 2026-04-03)  
> **Scope**: Separate the "Board" entity (which acts as a project container) from the
> "Board" view (the Kanban task board), or at minimum relabel the UI to remove the
> ambiguity.

---

## 1. Problem Statement

Today the word **"Board"** is overloaded with two different meanings:

| Meaning | What it actually is | Where it appears |
|---------|---------------------|------------------|
| **Project** | The top-level organisational unit that owns tasks, channels, plans, sprints, agents, webhooks, and settings. | Backend `Board` model, `boards` table, sidebar nav, URLs, API routes. |
| **Task Board** | The Kanban-style column view at `/boards/{id}` where tasks are dragged between statuses. | The `TaskBoard` component, the main `/boards/[boardId]/page.tsx` route. |

When a user clicks **"Boards"** in the sidebar they expect a Kanban board, but what they
are actually selecting is a _project_ — because everything else (Channels, Planning,
Sprints, Approvals) is scoped to that same entity. Creating a "new board" creates a
whole project, not just a column layout.

### Symptoms of the confusion

1. The sidebar section is labelled **"Projects"** but the link inside it is **"Boards"**.
2. The `BoardSelectorSidebar` (used by Planning and Sprints) has the heading
   **"Boards"** — users selecting a sidebar item in the _Sprints_ screen don't think
   they're picking a "board". _(Note: Channels does not currently use
   `BoardSelectorSidebar`.)_
3. The "Create board" page (`/boards/new`) asks for a gateway, description, and group —
   settings that relate to a _project_ rather than a visual board layout.
4. "Board Groups" in Administration are really _project groups / portfolios_.

---

## 2. Proposed Terminology

| Current term | New term | Notes |
|---|---|---|
| Board (the entity) | **Project** | The top-level container. |
| Board (the Kanban view) | **Task Board** | The UI component stays as-is; it's the _view_ into a project's tasks. |
| board_id (in URLs) | **projectId** | Only change if we go to Phase 2. |
| Board Groups | **Project Groups** (or **Portfolios**) | Rename the Administration menu item and API label. |
| BoardSelectorSidebar heading "Boards" | **Projects** | Change immediately in Phase 1. |
| "Create board" | **"Create project"** | Change form title, button text, description copy. |
| Sidebar nav item "Boards" | **"Task Board"** | Navigates to the Kanban view for the selected project. |

---

## 3. Phased Approach

### Phase 1 — UI-only relabelling (low risk, no migrations)

Change labels, headings, and copy throughout the frontend. No backend model renames,
no database migrations, no API route changes. This is purely cosmetic and can be
shipped in a single PR.

#### 3.1 Files to change

##### 3.1.1 Main navigation & user menu

| File | Change |
|------|--------|
| `DashboardSidebar.tsx` | Sidebar link "Boards" → **"Task Board"**; "Board Groups" → **"Project Groups"**; keep "Projects" section heading. |
| `UserMenu.tsx` | "Open boards" → **"Open projects"**; "Create board" → **"Create project"**. |
| `UserMenu.test.tsx` | Update aria-query assertions: `"open boards"` → `"open projects"`, `"create board"` → `"create project"`. |
| `BoardSelectorSidebar.tsx` | Heading "Boards" → **"Projects"**; `aria-label` "Board selector" → "Project selector"; "New board" → **"New project"**; "No boards." → "No projects." |

##### 3.1.2 Project CRUD routes

| File | Change |
|------|--------|
| `boards/page.tsx` | CTA "No boards yet" → "No projects yet"; link → "Create your first project". _(Note: mostly a redirect route; minimal copy.)_ |
| `boards/new/page.tsx` | Title "Create board" → **"Create project"**; description → "Projects organize tasks, agents, and sprints by mission context."; "Board name" → "Project name"; button "Create board" → "Create project"; "Board group" → "Project group". |
| `boards/[boardId]/edit/page.tsx` | Heading "Board settings" → **"Project settings"**; field labels accordingly; toast messages. Full audit — many strings throughout (~400 lines). |

##### 3.1.3 Main board route (`boards/[boardId]/page.tsx`)

This file has significant surface area beyond the header. All of the following must be addressed:

| Region | Strings to change |
|--------|-------------------|
| Heading fallback | `"Board"` fallback → **"Project"** |
| Status badge | `"Provisioning board lead…"` → **"Provisioning project lead…"** _(see §3.1.9 for decision)_ |
| View toggle | `"Board"` button label → **"Task Board"** |
| Chat icons | `aria-label="Board chat"`, `title="Board chat"` → see §3.1.9 |
| Settings icon | `aria-label="Board settings"`, `title="Board settings"` → **"Project settings"** |
| Approvals panel | `"… pending on this board."`, `"No pending approvals on this board."` → **"… on this project."** |
| Read-only notice | `"… cannot post comments on this board."` → **"… on this project."** |
| Chat slide-over | `"Board chat"` heading, `"Close board chat"` aria-label → see §3.1.9 |
| Chat placeholder | `"Message the board lead…"` → see §3.1.9 |
| Live feed | `"… board-chat activity."` → see §3.1.9 |
| Pause/Resume dialogs | `"Send /pause to every agent on this board."` etc. → **"… on this project."** |
| Broadcast explainer | `"to board chat."`, `"… forwards it to all agents on this board."` → see §3.1.9 |

##### 3.1.4 Shared components

| File | Change |
|------|--------|
| `TaskCustomFieldsEditor.tsx` | `"No custom fields configured for this board."` → **"… for this project."** |
| `BoardTemplateEditor.tsx` | `"Board override"` → **"Project override"**; `"Board template overrides"` heading → **"Project template overrides"**; section description → "… on this project."; remove confirmation prompt → "Remove the project override for …?"; keep Jinja2 variable _names_ (`board_name`, `board_goal`) unchanged — only change their _description_ text. |

##### 3.1.5 Board-group / project-group routes

| File | Change |
|------|--------|
| `board-groups/new/page.tsx` | Page title "Create board group" → **"Create project group"**; description, labels, placeholders, helper text: replace every "board(s)" with "project(s)". ~12 strings. |
| `board-groups/[groupId]/edit/page.tsx` | "Sign in to edit board groups." → "… project groups."; section labels, description, search placeholder, empty-state text: ~10 strings. |
| `board-groups/[groupId]/page.tsx` | Eyebrow "Board group" → **"Project group"**; "View boards" → "View projects"; "Top tasks per board" → "per project"; empty state "No boards in this group…" → "No projects in this group…"; link titles "Open board" → "Open project"; "Open task on board" → "Open task in project". |

##### 3.1.6 Admin & access-management surfaces

| File | Change |
|------|--------|
| `custom-fields/[fieldId]/edit/page.tsx` | `"… board bindings."` → **"… project bindings."** |
| `CustomFieldForm.tsx` | `"Board bindings"` heading → **"Project bindings"**; `"Search boards…"` → "Search projects…"; `"Loading boards…"` → "Loading projects…"; `"No boards found."` → "No projects found."; helper text → "… in selected projects." |
| `AgentBoardAccessPanel.tsx` | `"Board access"` → **"Project access"**; `"Grant this standalone agent access to specific boards."` → "… projects."; field label `"Board"` → "Project"; placeholder `"Select board"` → "Select project"; fallback `"Board {id}"` → "Project {id}"; empty states → "No project access granted yet.", "Grant access to projects above…". |
| `agents/[agentId]/page.tsx` | Tab label `"Board access"` → **"Project access"**; overview field `"Board"` → "Project"; `"Gateway main (no board)"` → "Gateway main (no project)". |

##### 3.1.7 Activity & webhook routes

| File | Change |
|------|--------|
| `activity/page.tsx` | Feed card titles: `"Board command"` / `"Board chat"` → see §3.1.9; event message `"… joined this board."` → **"… joined this project."**; page description → "… project-chat activity across all projects." |
| `webhooks/[webhookId]/payloads/page.tsx` | `"Back to board settings"` → **"Back to project settings"**. |

##### 3.1.8 Empty-state copy

| File | Change |
|------|--------|
| `channels/page.tsx` | Any "board" → "project" in empty state. |
| `planning/page.tsx` | Same. |
| `sprints/page.tsx` | Same. |

##### 3.1.9 Terminology decisions required before implementation

The following terms are **not** simple "board → project" replacements. Each needs an
explicit decision before any code is changed:

| Current term | Options | Recommendation | Decision |
|---|---|---|---|
| **Board chat** | "Project chat", "Team chat", "Chat" | **"Project chat"** — consistent, clear scope | _TBD_ |
| **Board lead** | "Project lead", "Lead agent" | **"Project lead"** — mirrors "Project" consistently | _TBD_ |
| **Board goal** | "Project goal", "Mission goal", "Objective" | **"Project goal"** — straightforward | _TBD_ |
| **Platform board** | "Platform project", "System project" | **"Platform project"** | _TBD_ |
| **Board command** (activity feed) | "Project command", "Chat command" | **"Project command"** | _TBD_ |

> **Action**: Fill in the "Decision" column before starting implementation.
> These decisions affect ~30 strings across 6+ files.

#### 3.2 Things that do NOT change in Phase 1

- URL paths (`/boards/...`) — remain stable so no links break.
- Backend model names (`Board`, `BoardGroup`, table `boards`).
- API route prefixes (`/api/v1/boards/{board_id}/...`).
- Internal variable / prop / component names (`boardId`, `BoardSelectorSidebar`, etc.).
- Database column names.

#### 3.3 How to find every user-facing string

```bash
# From the repo root — finds all user-visible "board" text in the frontend.
grep -rn --include='*.tsx' --include='*.ts' \
  -iE '"[^"]*board[^"]*"|'\''[^'\'']*board[^'\'']*'\''|`[^`]*board[^`]*`' \
  frontend/src/ | grep -vi 'import\|from\|type\|interface\|const\|onboard'
```

Manually review each hit; only change strings that appear in JSX text content,
`title=`, `description=`, `placeholder=`, `aria-label=`, or `label` props.

---

### Phase 2 — Frontend URL rename (medium risk)

Rename the URL namespace from `/boards/...` to `/projects/...` and add permanent
redirects so bookmarks and external links keep working.

#### 4.1 URL mapping

| Old route | New route |
|-----------|-----------|
| `/boards` | `/projects` |
| `/boards/new` | `/projects/new` |
| `/boards/[boardId]` | `/projects/[projectId]` |
| `/boards/[boardId]/edit` | `/projects/[projectId]/settings` |
| `/boards/[boardId]/approvals` | `/projects/[projectId]/approvals` |
| `/boards/[boardId]/webhooks/...` | `/projects/[projectId]/webhooks/...` |
| `/board-groups` | `/project-groups` |
| `/channels/[boardId]` | `/channels/[projectId]` |
| `/planning/[boardId]` | `/planning/[projectId]` |
| `/sprints/[boardId]` | `/sprints/[projectId]` |

#### 4.2 Redirect strategy

Add a `next.config.ts` redirect block:

```ts
redirects: async () => [
  { source: "/boards/:path*",         destination: "/projects/:path*",       permanent: true },
  { source: "/board-groups/:path*",   destination: "/project-groups/:path*", permanent: true },
],
```

This keeps old bookmarks working indefinitely.

#### 4.3 Internal link audit

Every `href` and `router.push`/`router.replace` referencing `/boards` must be updated.
Use a codemod or exhaustive grep:

```bash
grep -rn '/boards' frontend/src/ --include='*.tsx' --include='*.ts'
```

#### 4.4 Param rename (`boardId` → `projectId` in page components)

All `useParams()` and dynamic route segments `[boardId]` become `[projectId]`.  
Component props that accept `boardId` should be aliased:

```ts
type Props = { projectId: string };
// Internally still calls API with boardId until Phase 3.
```

---

### Phase 3 — Backend rename (high risk, requires migration + API versioning)

Rename the backend model, table, and API routes. This is optional and should only be
done if the mismatch between API naming and UI naming causes developer confusion.

#### 5.1 Database migration

```sql
ALTER TABLE boards RENAME TO projects;
ALTER TABLE board_groups RENAME TO project_groups;
-- Rename FK columns across all referencing tables:
ALTER TABLE tasks RENAME COLUMN board_id TO project_id;
ALTER TABLE sprints RENAME COLUMN board_id TO project_id;
ALTER TABLE plans RENAME COLUMN board_id TO project_id;
-- etc. for every table with board_id
```

**Risk**: Every backend query, model relationship, and index references `board_id`.
This migration touches 20+ tables.

#### 5.2 API route change

| Old | New |
|-----|-----|
| `/api/v1/boards` | `/api/v1/projects` |
| `/api/v1/boards/{board_id}/tasks` | `/api/v1/projects/{project_id}/tasks` |
| `/api/v1/boards/{board_id}/sprints` | `/api/v1/projects/{project_id}/sprints` |
| `/api/v1/boards/{board_id}/plans` | `/api/v1/projects/{project_id}/plans` |
| `/api/v1/board-groups` | `/api/v1/project-groups` |

To avoid breaking callers, keep the old routes as thin aliases for one release cycle:

```python
# Deprecated aliases
boards_compat = APIRouter(prefix="/boards", deprecated=True)

@boards_compat.get("/{board_id}/tasks")
async def compat_list_tasks(board_id: UUID, ...):
    return await list_tasks(project_id=board_id, ...)
```

#### 5.3 Model & schema rename

- `Board` → `Project`; `BoardGroup` → `ProjectGroup`
- All Pydantic schemas: `BoardRead` → `ProjectRead`, `BoardCreate` → `ProjectCreate`, etc.
- Regenerate the frontend API client (`make api-gen`).

#### 5.4 Template / webhook rename

Backend templates like `BOARD_AGENTS.md.j2`, `BOARD_SOUL.md.j2`, etc. reference
"board" in their filenames and content variables. These would need a corresponding
rename pass.

---

## 4. Recommended Strategy

**Ship Phase 1 now.** It eliminates the user-facing confusion with zero backend risk.
Defer Phase 2 (URL rename) to a follow-up sprint once Phase 1 is validated in
production. Treat Phase 3 (backend rename) as a long-term housekeeping item — only
pursue it if the board/project mismatch causes real developer friction.

### Phase 1 implementation checklist

#### Pre-flight
- [ ] **Resolve terminology decisions** (§3.1.9) before changing any code

#### Navigation & menus
- [ ] Sidebar section heading stays "Projects" (already correct)
- [ ] Sidebar nav link "Boards" → "Task Board"
- [ ] Sidebar "Board Groups" → "Project Groups"
- [ ] `UserMenu.tsx`: "Open boards" → "Open projects"
- [ ] `UserMenu.tsx`: "Create board" → "Create project"
- [ ] `BoardSelectorSidebar` heading "Boards" → "Projects"
- [ ] `BoardSelectorSidebar` "New board" → "New project"
- [ ] `BoardSelectorSidebar` "No boards." → "No projects."

#### Project CRUD routes
- [ ] `/boards/new` page: title, description, field labels, button
- [ ] `/boards/[boardId]/edit` page: heading, field labels, toast messages (~400 lines)
- [ ] `/boards` empty state copy

#### Main board route (`/boards/[boardId]`)
- [ ] Heading fallback "Board" → "Project"
- [ ] Status badge "Provisioning board lead…" → per terminology decision
- [ ] View toggle "Board" → "Task Board"
- [ ] Chat icon aria/title → per terminology decision
- [ ] Settings icon aria/title → "Project settings"
- [ ] Approvals panel copy → "… on this project."
- [ ] Read-only notice → "… on this project."
- [ ] Chat slide-over heading + close button
- [ ] Chat placeholder
- [ ] Live-feed description
- [ ] Pause/Resume dialog copy
- [ ] Broadcast explainer copy

#### Shared components
- [ ] `TaskCustomFieldsEditor` empty state → "… for this project."
- [ ] `BoardTemplateEditor` — override labels, heading, description, confirm prompt; keep Jinja2 variable names

#### Board-group / project-group routes
- [ ] `/board-groups/new` — page title, description, labels, placeholders, helper text (~12 strings)
- [ ] `/board-groups/[groupId]/edit` — sign-in msg, labels, description, placeholders (~10 strings)
- [ ] `/board-groups/[groupId]` — eyebrow, links, filter labels, empty state, link titles (~8 strings)
- [ ] Administration sidebar link "Board Groups" → "Project Groups"

#### Admin & access-management surfaces
- [ ] `custom-fields/[fieldId]/edit` — page description → "… project bindings."
- [ ] `CustomFieldForm` — heading, search, loading, empty, helper (~5 strings)
- [ ] `AgentBoardAccessPanel` — heading, description, labels, placeholders, empty states (~10 strings)
- [ ] `agents/[agentId]` — tab label, overview field, fallback text

#### Activity & webhooks
- [ ] `activity/page.tsx` — feed card titles, event messages, page description
- [ ] `webhooks/[webhookId]/payloads` — "Back to board settings" → "Back to project settings"

#### Empty-state copy
- [ ] `/channels` empty state
- [ ] `/planning` empty state
- [ ] `/sprints` empty state

#### Tests
- [ ] `UserMenu.test.tsx` — update aria assertions
- [ ] `mobile_sidebar.cy.ts` — update `cy.contains("a", "Boards")` assertion
- [ ] `boards_list.cy.ts` — update `/create board/i` and `/boards/i` assertions

#### Documentation & screenshots
- [ ] `docs/screenshots/01-boards.png` — retake after UI changes
- [ ] Update any doc/README references to "board" that face operators

#### Final audit
- [ ] Grep-audit all remaining user-facing "board" strings in `frontend/src/`
- [ ] No changes to backend, API routes, database, or internal variable names

### Phase 1 verification checklist

After implementation, verify each surface manually or via automated tests:

#### UI smoke checks
| Surface | What to verify |
|---------|----------------|
| `DashboardSidebar` | "Projects" section heading, "Task Board" link, "Project Groups" link |
| `UserMenu` | "Open projects" and "Create project" links |
| `BoardSelectorSidebar` | "Projects" heading, "New project" link, "No projects." empty state |

#### Route checks
| Route | What to verify |
|-------|----------------|
| `/boards` | Empty state says "projects" |
| `/boards/new` | All form labels, title, button say "project" |
| `/boards/[boardId]` | Heading, view toggle, chat panel, approvals, dialogs |
| `/boards/[boardId]/edit` | All settings headings and labels |
| `/channels` | Empty state says "project" |
| `/planning` | Empty state says "project" |
| `/sprints` | Empty state says "project" |
| `/board-groups/new` | All form labels and helper text |
| `/board-groups/[groupId]` | Eyebrow, links, empty state |
| `/board-groups/[groupId]/edit` | Labels, description, search placeholder |
| `/activity` | Feed card titles, page description |
| `/agents/[agentId]` | "Project access" tab, overview field |
| `/custom-fields/[fieldId]/edit` | Page description |

#### Test passes
| Test file | Expected outcome |
|-----------|------------------|
| `UserMenu.test.tsx` | Updated assertions pass |
| `mobile_sidebar.cy.ts` | Sidebar link text matches new labels |
| `boards_list.cy.ts` | Heading/button assertions match new labels |
| Full `npm run test` | No regressions |
| Full `npm run build` | No build errors |

### Estimated effort

| Phase | Size | Risk |
|-------|------|------|
| Phase 1 — UI relabelling | ~2–4 hours | Very low |
| Phase 2 — URL rename + redirects | ~1 day | Low-medium (redirect coverage) |
| Phase 3 — Backend rename | ~2–3 days | High (migration, API compat, client regen) |

---

## 5. Open Questions

1. **Should "Task Board" be renamed to just "Board"?** — "Task Board" is more
   descriptive but longer. Since we are freeing up the word "Board" from the project
   sense, keeping it as "Board" for the Kanban view is also viable (users intuitively
   understand "board" = columns of cards).
2. **Board Groups → Project Groups or Portfolios?** — "Project Groups" is the safe
   parallel rename. "Portfolios" is more product-y but diverges further and may need
   its own justification.
3. **Should the sidebar combine "Task Board" into a sub-item of each project?** — Long
   term it might make sense to have a project-level landing page with tabs (Board ·
   Channels · Planning · Sprints), but that's a larger IA change beyond a rename.
4. **Timing vs. other in-flight feature work?** — Phase 1 touches many of the same
   files as the ongoing sprint/backlog and channels features. Best to merge those
   first, then apply the rename on a clean master.
