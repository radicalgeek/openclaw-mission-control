/**
 * Manual API client for board/org template override endpoints.
 * These are new endpoints not yet in the generated client.
 */
import { customFetch, ApiError } from "@/api/mutator";

export type TemplateSource = "board" | "org" | "built-in";

export interface BoardTemplateRead {
  id: string;
  organization_id: string;
  board_id: string | null;
  file_name: string;
  template_content: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  source: TemplateSource;
}

export interface BoardTemplateUpsert {
  template_content: string;
}

export interface BoardTemplatePreviewRequest {
  template_content: string;
  agent_id?: string | null;
}

export interface BoardTemplatePreviewResponse {
  rendered: string;
  file_name: string;
}

/** List all template overrides for a board (board-level). */
export const listBoardTemplates = async (
  boardId: string,
): Promise<{ data: BoardTemplateRead[]; status: number }> => {
  return customFetch<{ data: BoardTemplateRead[]; status: number }>(
    `/api/v1/boards/${boardId}/templates`,
    { method: "GET" },
  );
};

/** Upsert a board-level template override. */
export const upsertBoardTemplate = async (
  boardId: string,
  fileName: string,
  body: BoardTemplateUpsert,
): Promise<{ data: BoardTemplateRead; status: number }> => {
  return customFetch<{ data: BoardTemplateRead; status: number }>(
    `/api/v1/boards/${boardId}/templates/${encodeURIComponent(fileName)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
};

/** Get a single board-level template override. */
export const getBoardTemplate = async (
  boardId: string,
  fileName: string,
): Promise<{ data: BoardTemplateRead; status: number }> => {
  return customFetch<{ data: BoardTemplateRead; status: number }>(
    `/api/v1/boards/${boardId}/templates/${encodeURIComponent(fileName)}`,
    { method: "GET" },
  );
};

/** Delete a board-level template override. */
export const deleteBoardTemplate = async (
  boardId: string,
  fileName: string,
): Promise<{ data: undefined; status: number }> => {
  return customFetch<{ data: undefined; status: number }>(
    `/api/v1/boards/${boardId}/templates/${encodeURIComponent(fileName)}`,
    { method: "DELETE" },
  );
};

/** Preview rendered output of a template. */
export const previewBoardTemplate = async (
  boardId: string,
  fileName: string,
  body: BoardTemplatePreviewRequest,
): Promise<{ data: BoardTemplatePreviewResponse; status: number }> => {
  return customFetch<{ data: BoardTemplatePreviewResponse; status: number }>(
    `/api/v1/boards/${boardId}/templates/${encodeURIComponent(fileName)}/preview`,
    { method: "POST", body: JSON.stringify(body) },
  );
};

/** List org-wide template overrides. */
export const listOrgTemplates = async (): Promise<{
  data: BoardTemplateRead[];
  status: number;
}> => {
  return customFetch<{ data: BoardTemplateRead[]; status: number }>(
    `/api/v1/org-templates`,
    { method: "GET" },
  );
};

/** Upsert an org-wide template override. */
export const upsertOrgTemplate = async (
  fileName: string,
  body: BoardTemplateUpsert,
): Promise<{ data: BoardTemplateRead; status: number }> => {
  return customFetch<{ data: BoardTemplateRead; status: number }>(
    `/api/v1/org-templates/${encodeURIComponent(fileName)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
};

/** Delete an org-wide template override. */
export const deleteOrgTemplate = async (
  fileName: string,
): Promise<{ data: undefined; status: number }> => {
  return customFetch<{ data: undefined; status: number }>(
    `/api/v1/org-templates/${encodeURIComponent(fileName)}`,
    { method: "DELETE" },
  );
};

export { ApiError };
