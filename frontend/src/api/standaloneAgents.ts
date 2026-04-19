/**
 * Hand-written API client for standalone-agent endpoints.
 * Covers: agent webhooks, board access grants, and skill allowlist.
 * Uses the same customFetch pattern as the generated API clients.
 */
import { customFetch } from "./mutator";

// ─── Shared ───────────────────────────────────────────────────────────────────

export type AgentType =
  | "board_worker"
  | "board_lead"
  | "gateway_main"
  | "standalone";

// ─── Agent Webhooks ──────────────────────────────────────────────────────────

export interface AgentWebhookRead {
  id: string;
  agent_id: string;
  organization_id: string;
  description: string;
  enabled: boolean;
  endpoint_path: string;
  endpoint_url: string | null;
  has_secret: boolean;
  signature_header: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentWebhookCreate {
  description?: string;
  enabled?: boolean;
  secret?: string | null;
  signature_header?: string | null;
}

export interface AgentWebhookUpdate {
  description?: string;
  enabled?: boolean;
  secret?: string | null;
  signature_header?: string | null;
}

export interface AgentWebhookPayloadRead {
  id: string;
  agent_id: string;
  webhook_id: string;
  payload: unknown;
  headers: Record<string, string> | null;
  source_ip: string | null;
  content_type: string | null;
  received_at: string;
}

export const listAgentWebhooks = (agentId: string) =>
  customFetch<{ data: AgentWebhookRead[]; status: number }>(
    `/api/v1/agents/${agentId}/webhooks`,
    { method: "GET" },
  );

export const createAgentWebhook = (agentId: string, body: AgentWebhookCreate) =>
  customFetch<{ data: AgentWebhookRead; status: number }>(
    `/api/v1/agents/${agentId}/webhooks`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const updateAgentWebhook = (
  agentId: string,
  webhookId: string,
  body: AgentWebhookUpdate,
) =>
  customFetch<{ data: AgentWebhookRead; status: number }>(
    `/api/v1/agents/${agentId}/webhooks/${webhookId}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );

export const deleteAgentWebhook = (agentId: string, webhookId: string) =>
  customFetch<{ data: { ok: boolean }; status: number }>(
    `/api/v1/agents/${agentId}/webhooks/${webhookId}`,
    { method: "DELETE" },
  );

export const listAgentWebhookPayloads = (
  agentId: string,
  webhookId: string,
  limit = 20,
) =>
  customFetch<{ data: { items: AgentWebhookPayloadRead[] }; status: number }>(
    `/api/v1/agents/${agentId}/webhooks/${webhookId}/payloads?limit=${limit}`,
    { method: "GET" },
  );

// ─── Board Access Grants ─────────────────────────────────────────────────────

export interface AgentBoardAccessRead {
  id: string;
  agent_id: string;
  board_id: string;
  access_level: "read" | "write";
  created_at: string;
}

export interface AgentBoardAccessCreate {
  board_id: string;
  access_level?: "read" | "write";
}

export const listAgentBoardAccess = (agentId: string) =>
  customFetch<{ data: AgentBoardAccessRead[]; status: number }>(
    `/api/v1/agents/${agentId}/board-access`,
    { method: "GET" },
  );

export const createAgentBoardAccess = (
  agentId: string,
  body: AgentBoardAccessCreate,
) =>
  customFetch<{ data: AgentBoardAccessRead; status: number }>(
    `/api/v1/agents/${agentId}/board-access`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const deleteAgentBoardAccess = (agentId: string, grantId: string) =>
  customFetch<{ data: { ok: boolean }; status: number }>(
    `/api/v1/agents/${agentId}/board-access/${grantId}`,
    { method: "DELETE" },
  );

// ─── Skills Allowlist ─────────────────────────────────────────────────────────

export interface AgentSkillsRead {
  agent_id: string;
  installed_skills: string[] | null;
}

export interface AgentSkillsUpdate {
  installed_skills: string[] | null;
}

export const getAgentSkills = (agentId: string) =>
  customFetch<{ data: AgentSkillsRead; status: number }>(
    `/api/v1/agents/${agentId}/skills`,
    { method: "GET" },
  );

export const updateAgentSkills = (agentId: string, body: AgentSkillsUpdate) =>
  customFetch<{ data: AgentSkillsRead; status: number }>(
    `/api/v1/agents/${agentId}/skills`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
