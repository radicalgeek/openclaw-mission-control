/**
 * Hand-written API client for the Planning feature endpoints.
 * Uses the same customFetch pattern as the generated API clients.
 */
import { customFetch } from "./mutator";

// ─── Types ───────────────────────────────────────────────────────────────────

type ApiResponse<T> = { data: T; status: number; headers: Headers };

export type PlanStatus = "draft" | "active" | "completed" | "archived";

export type PlanMessage = {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
};

export type PlanRead = {
  id: string;
  board_id: string;
  title: string;
  slug: string;
  content: string;
  status: PlanStatus;
  created_by_user_id: string | null;
  task_id: string | null;
  task_status: string | null;
  session_key: string;
  messages: PlanMessage[] | null;
  created_at: string;
  updated_at: string;
};

export type PlanCreate = {
  title: string;
  initial_prompt?: string;
};

export type PlanUpdate = {
  title?: string;
  content?: string;
  status?: PlanStatus;
};

export type PlanChatRequest = {
  message: string;
};

export type PlanChatResponse = {
  plan: PlanRead;
  agent_reply: string | null;
};

export type PlanPromoteRequest = {
  task_title?: string;
  task_priority?: string;
  assigned_agent_id?: string;
};

// ─── API Functions ────────────────────────────────────────────────────────────

const base = (boardId: string) => `/api/v1/boards/${boardId}/plans`;

export const listPlans = (
  boardId: string,
  status?: PlanStatus,
): Promise<ApiResponse<PlanRead[]>> => {
  const url = status ? `${base(boardId)}?status=${status}` : base(boardId);
  return customFetch<ApiResponse<PlanRead[]>>(url, { method: "GET" });
};

export const createPlan = (
  boardId: string,
  payload: PlanCreate,
): Promise<ApiResponse<PlanRead>> =>
  customFetch<ApiResponse<PlanRead>>(base(boardId), {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getPlan = (
  boardId: string,
  planId: string,
): Promise<ApiResponse<PlanRead>> =>
  customFetch<ApiResponse<PlanRead>>(`${base(boardId)}/${planId}`, {
    method: "GET",
  });

export const updatePlan = (
  boardId: string,
  planId: string,
  payload: PlanUpdate,
): Promise<ApiResponse<PlanRead>> =>
  customFetch<ApiResponse<PlanRead>>(`${base(boardId)}/${planId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const deletePlan = (
  boardId: string,
  planId: string,
): Promise<ApiResponse<{ ok: boolean }>> =>
  customFetch<ApiResponse<{ ok: boolean }>>(`${base(boardId)}/${planId}`, {
    method: "DELETE",
  });

export const chatWithPlan = (
  boardId: string,
  planId: string,
  payload: PlanChatRequest,
): Promise<ApiResponse<PlanChatResponse>> =>
  customFetch<ApiResponse<PlanChatResponse>>(
    `${base(boardId)}/${planId}/chat`,
    { method: "POST", body: JSON.stringify(payload) },
  );

export const promotePlan = (
  boardId: string,
  planId: string,
  payload?: PlanPromoteRequest,
): Promise<ApiResponse<PlanRead>> =>
  customFetch<ApiResponse<PlanRead>>(
    `${base(boardId)}/${planId}/promote`,
    { method: "POST", body: JSON.stringify(payload ?? {}) },
  );

