/**
 * Manual API client for agent workspace file endpoints.
 * These are new endpoints not yet in the generated client.
 */
import { customFetch, ApiError } from "@/api/mutator";

export interface AgentFileEntry {
  name: string;
  missing: boolean;
}

export interface AgentFileList {
  files: AgentFileEntry[];
}

export interface AgentFileContent {
  name: string;
  content: string;
  missing: boolean;
}

export interface AgentFileWrite {
  content: string;
}

export const listAgentFiles = async (
  agentId: string,
): Promise<{ data: AgentFileList; status: number }> => {
  return customFetch<{ data: AgentFileList; status: number }>(
    `/api/v1/agents/${agentId}/files`,
    { method: "GET" },
  );
};

export const getAgentFile = async (
  agentId: string,
  fileName: string,
): Promise<{ data: AgentFileContent; status: number }> => {
  return customFetch<{ data: AgentFileContent; status: number }>(
    `/api/v1/agents/${agentId}/files/${encodeURIComponent(fileName)}`,
    { method: "GET" },
  );
};

export const setAgentFile = async (
  agentId: string,
  fileName: string,
  body: AgentFileWrite,
  resetSession?: boolean,
): Promise<{ data: AgentFileContent; status: number }> => {
  const qs = resetSession ? "?reset_session=true" : "";
  return customFetch<{ data: AgentFileContent; status: number }>(
    `/api/v1/agents/${agentId}/files/${encodeURIComponent(fileName)}${qs}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
};

export const deleteAgentFile = async (
  agentId: string,
  fileName: string,
): Promise<{ data: AgentFileContent | undefined; status: number }> => {
  return customFetch<{ data: AgentFileContent | undefined; status: number }>(
    `/api/v1/agents/${agentId}/files/${encodeURIComponent(fileName)}`,
    { method: "DELETE" },
  );
};

export { ApiError };
