/**
 * Hand-written API client for the Channels feature endpoints.
 * Uses the same customFetch pattern as the generated API clients.
 *
 * Field names match the actual backend schemas exactly.
 */
import { customFetch } from "./mutator";

// ─── Types ───────────────────────────────────────────────────────────────────

export type ChannelType = "alert" | "discussion" | "direct";

/**
 * Direct channels use webhook_source_filter to store the target agent's UUID.
 * This is intentional – direct channels never receive webhook events.
 */
export type DirectChannelAgentId = string; // UUID

export type ChannelRead = {
  id: string;
  board_id: string;
  name: string;
  slug: string;
  channel_type: ChannelType;
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

export type ChannelCreate = {
  name: string;
  description?: string;
  channel_type?: ChannelType;
  is_readonly?: boolean;
  position?: number;
  webhook_source_filter?: string | null;
};

type ApiResponse<T> = { data: T; status: number; headers: Headers };

// ─── Board Channels ───────────────────────────────────────────────────────────

export const getBoardChannels = (
  boardId: string,
): Promise<ApiResponse<ChannelRead[]>> =>
  customFetch<ApiResponse<ChannelRead[]>>(
    `/api/v1/boards/${boardId}/channels`,
    { method: "GET" },
  );

export const createChannel = (
  boardId: string,
  payload: ChannelCreate,
): Promise<ApiResponse<ChannelRead>> =>
  customFetch<ApiResponse<ChannelRead>>(
    `/api/v1/boards/${boardId}/channels`,
    { method: "POST", body: JSON.stringify(payload) },
  );

export const deleteChannel = (
  channelId: string,
): Promise<ApiResponse<{ ok: boolean }>> =>
  customFetch<ApiResponse<{ ok: boolean }>>(
    `/api/v1/channels/${channelId}`,
    { method: "DELETE" },
  );

// ─── Channel ──────────────────────────────────────────────────────────────────

export const getChannel = (
  channelId: string,
): Promise<ApiResponse<ChannelRead>> =>
  customFetch<ApiResponse<ChannelRead>>(
    `/api/v1/channels/${channelId}`,
    { method: "GET" },
  );

export const markChannelRead = (
  channelId: string,
): Promise<ApiResponse<{ ok: boolean }>> =>
  customFetch<ApiResponse<{ ok: boolean }>>(
    `/api/v1/channels/${channelId}/mark-read`,
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
    `/api/v1/channels/${channelId}/threads${query ? `?${query}` : ""}`,
    { method: "GET" },
  );
};

export const createThread = (
  channelId: string,
  payload: ThreadCreate,
): Promise<ApiResponse<ThreadRead>> =>
  customFetch<ApiResponse<ThreadRead>>(
    `/api/v1/channels/${channelId}/threads`,
    { method: "POST", body: JSON.stringify(payload) },
  );

export const getThread = (
  threadId: string,
): Promise<ApiResponse<ThreadRead>> =>
  customFetch<ApiResponse<ThreadRead>>(
    `/api/v1/threads/${threadId}`,
    { method: "GET" },
  );

export const updateThread = (
  threadId: string,
  payload: ThreadUpdate,
): Promise<ApiResponse<ThreadRead>> =>
  customFetch<ApiResponse<ThreadRead>>(
    `/api/v1/threads/${threadId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );

/**
 * Create a new board task from this thread and link them bidirectionally.
 * The thread topic becomes the task title. Returns the updated thread with task_id set.
 */
export const createTaskFromThread = (
  threadId: string,
): Promise<ApiResponse<ThreadRead>> =>
  customFetch<ApiResponse<ThreadRead>>(
    `/api/v1/threads/${threadId}/create-task`,
    { method: "POST" },
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
    `/api/v1/threads/${threadId}/messages${query ? `?${query}` : ""}`,
    { method: "GET" },
  );
};

export const sendMessage = (
  threadId: string,
  payload: ThreadMessageCreate,
): Promise<ApiResponse<ThreadMessageRead>> =>
  customFetch<ApiResponse<ThreadMessageRead>>(
    `/api/v1/threads/${threadId}/messages`,
    { method: "POST", body: JSON.stringify(payload) },
  );

// ─── Webhook info ─────────────────────────────────────────────────────────────

export type ChannelWebhookInfo = {
  webhook_url: string | null;
  webhook_secret: string;
};

export const getChannelWebhookInfo = (
  channelId: string,
): Promise<ApiResponse<ChannelWebhookInfo>> =>
  customFetch<ApiResponse<ChannelWebhookInfo>>(
    `/api/v1/channels/${channelId}/webhook-info`,
    { method: "GET" },
  );

export const regenerateChannelWebhookSecret = (
  channelId: string,
): Promise<ApiResponse<ChannelWebhookInfo>> =>
  customFetch<ApiResponse<ChannelWebhookInfo>>(
    `/api/v1/channels/${channelId}/regenerate-webhook-secret`,
    { method: "POST" },
  );

export type ChannelUpdate = {
  name?: string;
  description?: string;
  is_readonly?: boolean;
  position?: number;
};

export const updateChannel = (
  channelId: string,
  payload: ChannelUpdate,
): Promise<ApiResponse<ChannelRead>> =>
  customFetch<ApiResponse<ChannelRead>>(
    `/api/v1/channels/${channelId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );

// ─── Helpers ──────────────────────────────────────────────────────────────────

export const ALERT_CHANNEL_TYPES: readonly ChannelType[] = ["alert"] as const;

export const DISCUSSION_CHANNEL_TYPES: readonly ChannelType[] = ["discussion"] as const;

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
