/**
 * Hand-written API client for Sprint and Backlog endpoints.
 * Uses the same customFetch pattern as the generated API clients.
 */
import { customFetch } from "./mutator";

// ─── Types ───────────────────────────────────────────────────────────────────

type ApiResponse<T> = { data: T; status: number; headers: Headers };

export type TagRef = {
  id: string;
  name: string;
  slug: string;
  color: string;
};

export type SprintStatus = "draft" | "queued" | "active" | "completed" | "cancelled";

export type SprintRead = {
  id: string;
  board_id: string;
  name: string;
  slug: string;
  goal: string | null;
  position: number;
  status: SprintStatus;
  started_at: string | null;
  completed_at: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  ticket_count: number;
  tickets_done_count: number;
};

export type SprintCreate = {
  name: string;
  goal?: string;
};

export type SprintUpdate = {
  name?: string;
  goal?: string;
  position?: number;
  status?: SprintStatus;
};

export type TaskRead = {
  id: string;
  board_id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  due_at: string | null;
  assigned_agent_id: string | null;
  is_backlog: boolean;
  sprint_id: string | null;
  tags: TagRef[];
  tag_ids: string[];
  created_at: string;
  updated_at: string;
};

export type BacklogTaskCreate = {
  title: string;
  description?: string;
  priority?: "low" | "medium" | "high" | "critical";
  sprint_id?: string;
  assigned_agent_id?: string;
  tag_ids?: string[];
  due_at?: string | null;
};

export type BatchBacklogCreate = {
  tickets: BacklogTaskCreate[];
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

const sprintsBase = (boardId: string) => `/api/v1/boards/${boardId}/sprints`;
const backlogBase = (boardId: string) => `/api/v1/boards/${boardId}/backlog`;

// ─── Sprint CRUD ──────────────────────────────────────────────────────────────

export const listSprints = (
  boardId: string,
  status?: string,
): Promise<ApiResponse<SprintRead[]>> => {
  const url = status
    ? `${sprintsBase(boardId)}?status=${status}`
    : sprintsBase(boardId);
  return customFetch<ApiResponse<SprintRead[]>>(url, { method: "GET" });
};

export const createSprint = (
  boardId: string,
  payload: SprintCreate,
): Promise<ApiResponse<SprintRead>> =>
  customFetch<ApiResponse<SprintRead>>(sprintsBase(boardId), {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getSprint = (
  boardId: string,
  sprintId: string,
): Promise<ApiResponse<SprintRead>> =>
  customFetch<ApiResponse<SprintRead>>(`${sprintsBase(boardId)}/${sprintId}`, {
    method: "GET",
  });

export const updateSprint = (
  boardId: string,
  sprintId: string,
  payload: SprintUpdate,
): Promise<ApiResponse<SprintRead>> =>
  customFetch<ApiResponse<SprintRead>>(
    `${sprintsBase(boardId)}/${sprintId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );

export const deleteSprint = (
  boardId: string,
  sprintId: string,
): Promise<ApiResponse<void>> =>
  customFetch<ApiResponse<void>>(`${sprintsBase(boardId)}/${sprintId}`, {
    method: "DELETE",
  });

// ─── Sprint Lifecycle ─────────────────────────────────────────────────────────

export const startSprint = (
  boardId: string,
  sprintId: string,
): Promise<ApiResponse<SprintRead>> =>
  customFetch<ApiResponse<SprintRead>>(
    `${sprintsBase(boardId)}/${sprintId}/start`,
    { method: "POST" },
  );

export const completeSprint = (
  boardId: string,
  sprintId: string,
): Promise<ApiResponse<SprintRead>> =>
  customFetch<ApiResponse<SprintRead>>(
    `${sprintsBase(boardId)}/${sprintId}/complete`,
    { method: "POST" },
  );

export const cancelSprint = (
  boardId: string,
  sprintId: string,
): Promise<ApiResponse<SprintRead>> =>
  customFetch<ApiResponse<SprintRead>>(
    `${sprintsBase(boardId)}/${sprintId}/cancel`,
    { method: "POST" },
  );

// ─── Sprint Tickets ───────────────────────────────────────────────────────────

export const listSprintTickets = (
  boardId: string,
  sprintId: string,
): Promise<ApiResponse<TaskRead[]>> =>
  customFetch<ApiResponse<TaskRead[]>>(
    `${sprintsBase(boardId)}/${sprintId}/tickets`,
    { method: "GET" },
  );

export const addSprintTickets = (
  boardId: string,
  sprintId: string,
  taskIds: string[],
): Promise<ApiResponse<unknown[]>> =>
  customFetch<ApiResponse<unknown[]>>(
    `${sprintsBase(boardId)}/${sprintId}/tickets`,
    { method: "POST", body: JSON.stringify({ task_ids: taskIds }) },
  );

export const removeSprintTicket = (
  boardId: string,
  sprintId: string,
  taskId: string,
): Promise<ApiResponse<unknown>> =>
  customFetch<ApiResponse<unknown>>(
    `${sprintsBase(boardId)}/${sprintId}/tickets/${taskId}`,
    { method: "DELETE" },
  );

// ─── Backlog ──────────────────────────────────────────────────────────────────

export const listBacklog = (
  boardId: string,
  opts?: { sprintId?: string; unassigned?: boolean },
): Promise<ApiResponse<TaskRead[]>> => {
  const params = new URLSearchParams();
  if (opts?.sprintId) params.set("sprint_id", opts.sprintId);
  if (opts?.unassigned) params.set("unassigned", "true");
  const qs = params.toString();
  const url = qs ? `${backlogBase(boardId)}?${qs}` : backlogBase(boardId);
  return customFetch<ApiResponse<TaskRead[]>>(url, { method: "GET" });
};

export const createBacklogTask = (
  boardId: string,
  payload: BacklogTaskCreate,
): Promise<ApiResponse<TaskRead>> =>
  customFetch<ApiResponse<TaskRead>>(backlogBase(boardId), {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const batchCreateBacklog = (
  boardId: string,
  payload: BatchBacklogCreate,
): Promise<ApiResponse<TaskRead[]>> =>
  customFetch<ApiResponse<TaskRead[]>>(`${backlogBase(boardId)}/batch`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ─── Tags ─────────────────────────────────────────────────────────────────────

export type PagedTags = {
  items: TagRef[];
  total: number;
  limit: number;
  offset: number;
};

export const listOrgTags = (
  limit = 200,
): Promise<ApiResponse<PagedTags>> =>
  customFetch<ApiResponse<PagedTags>>(`/api/v1/tags?limit=${limit}`, {
    method: "GET",
  });

// ─── Task update ──────────────────────────────────────────────────────────────

export type BacklogTaskUpdate = {
  title?: string;
  description?: string | null;
  priority?: string | null;
  due_at?: string | null;
  tag_ids?: string[] | null;
  status?: string | null;
};

export const updateBacklogTask = (
  boardId: string,
  taskId: string,
  payload: BacklogTaskUpdate,
): Promise<ApiResponse<TaskRead>> =>
  customFetch<ApiResponse<TaskRead>>(
    `/api/v1/boards/${boardId}/tasks/${taskId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
