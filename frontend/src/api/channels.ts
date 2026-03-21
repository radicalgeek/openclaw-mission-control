/**
 * Hand-written API client for the Channels feature endpoints.
 * Uses the same customFetch pattern as the generated API clients.
 *
 * Field names match the actual backend schemas exactly.
 */
import { customFetch } from "./mutator";

// ─── Types ───────────────────────────────────────────────────────────────────

export type ChannelRead = {
  id: string;
  board_id: string;
  name: string;
  slug: string;
  channel_type: string;
  description: string;
  is_archived: boolean;
  is_readonly: boolean;
  webhook_source_filter: string | null;
  position: number;
  created_at: string;
  updated_at: string;
  // Computed
  unread_count: number;
  last_message_preview: string | null;
};

/** content_type values as stored in the backend */
export type MessageContentType =
  | "text"
  | "webhook_event"
  | "agent_response"
  | "system_notification";

export type MessageSenderType = "user" | "agent" | "webhook" | "system";

/** Severity is stored in event_metadata.severity, not on the message directly */
export type MessageSeverity = "info" | "warning" | "error" | "critical";

export type ThreadMessageRead = {
  id: string;
  thread_id: string;
  sender_type: MessageSenderType;
  sender_id: string | null;
  sender_name: string;
  content: string;
  content_type: MessageContentType;
  event_metadata: Record<string, unknown> | null;
  is_edited: boolean;
  created_at: string;
  updated_at: string;
};

export type ThreadRead = {
  id: string;
  channel_id: string;
  topic: string;
  task_id: string | null;
  source_type: string;
  source_ref: string | null;
  is_resolved: boolean;
  is_pinned: boolean;
  message_count: number;
  last_message_at: string | null;
  last_message_preview: string | null;
  created_at: string;
  updated_at: string;
};

export type ThreadCreate = {
  topic: string;
  content: string; // Required: first message content
};

export type ThreadMessageCreate = {
  content: string;
  content_type?: MessageContentType;
};

export type ThreadUpdate = {
  is_resolved?: boolean;
  is_pinned?: boolean;
  topic?: string;
};

type ApiResponse<T> = { data: T; status: number; headers: Headers };

// ─── Board Channels ───────────────────────────────────────────────────────────

export const getBoardChannels = (
  boardId: string,
): Promise<ApiResponse<ChannelRead[]>> =>
  customFetch<ApiResponse<ChannelRead[]>>(
    `/api/boards/${boardId}/channels`,
    { method: "GET" },
  );

// ─── Channel ──────────────────────────────────────────────────────────────────

export const getChannel = (
  channelId: string,
): Promise<ApiResponse<ChannelRead>> =>
  customFetch<ApiResponse<ChannelRead>>(
    `/api/channels/${channelId}`,
    { method: "GET" },
  );

export const markChannelRead = (
  channelId: string,
): Promise<ApiResponse<{ ok: boolean }>> =>
  customFetch<ApiResponse<{ ok: boolean }>>(
    `/api/channels/${channelId}/mark-read`,
    { method: "POST" },
  );

// ─── Threads ──────────────────────────────────────────────────────────────────

export const getChannelThreads = (
  channelId: string,
  params?: {
    is_resolved?: boolean;
    pinned_only?: boolean;
    limit?: number;
    offset?: number;
  },
): Promise<ApiResponse<ThreadRead[]>> => {
  const qs = new URLSearchParams();
  if (params?.is_resolved != null) qs.set("is_resolved", String(params.is_resolved));
  if (params?.pinned_only) qs.set("pinned_only", "true");
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return customFetch<ApiResponse<ThreadRead[]>>(
    `/api/channels/${channelId}/threads${query ? `?${query}` : ""}`,
    { method: "GET" },
  );
};

export const createThread = (
  channelId: string,
  payload: ThreadCreate,
): Promise<ApiResponse<ThreadRead>> =>
  customFetch<ApiResponse<ThreadRead>>(
    `/api/channels/${channelId}/threads`,
    { method: "POST", body: JSON.stringify(payload) },
  );

export const getThread = (
  threadId: string,
): Promise<ApiResponse<ThreadRead>> =>
  customFetch<ApiResponse<ThreadRead>>(
    `/api/threads/${threadId}`,
    { method: "GET" },
  );

export const updateThread = (
  threadId: string,
  payload: ThreadUpdate,
): Promise<ApiResponse<ThreadRead>> =>
  customFetch<ApiResponse<ThreadRead>>(
    `/api/threads/${threadId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );

// ─── Messages ─────────────────────────────────────────────────────────────────

export const getThreadMessages = (
  threadId: string,
  params?: { limit?: number; before?: string },
): Promise<ApiResponse<ThreadMessageRead[]>> => {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.before) qs.set("before", params.before);
  const query = qs.toString();
  return customFetch<ApiResponse<ThreadMessageRead[]>>(
    `/api/threads/${threadId}/messages${query ? `?${query}` : ""}`,
    { method: "GET" },
  );
};

export const sendMessage = (
  threadId: string,
  payload: ThreadMessageCreate,
): Promise<ApiResponse<ThreadMessageRead>> =>
  customFetch<ApiResponse<ThreadMessageRead>>(
    `/api/threads/${threadId}/messages`,
    { method: "POST", body: JSON.stringify(payload) },
  );

// ─── Helpers ──────────────────────────────────────────────────────────────────

export const ALERT_CHANNEL_TYPES = [
  "build-alerts",
  "deployment-alerts",
  "test-run-alerts",
  "production-alerts",
] as const;

export const DISCUSSION_CHANNEL_TYPES = [
  "development",
  "devops",
  "testing",
  "architecture",
  "general",
] as const;

export const isAlertChannel = (channel: ChannelRead): boolean =>
  (ALERT_CHANNEL_TYPES as readonly string[]).includes(channel.channel_type);

export const isDiscussionChannel = (channel: ChannelRead): boolean =>
  (DISCUSSION_CHANNEL_TYPES as readonly string[]).includes(channel.channel_type);

/** Extract severity from event_metadata, defaulting to "info" */
export const getMessageSeverity = (msg: ThreadMessageRead): MessageSeverity => {
  if (!msg.event_metadata) return "info";
  const raw = msg.event_metadata.severity;
  if (raw === "warning" || raw === "error" || raw === "critical") return raw;
  return "info";
};
