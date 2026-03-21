import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ThreadMessageRead, ThreadRead } from "@/api/channels";

// ── Mock channels API ────────────────────────────────────────────────────────

const getThreadMessagesMock = vi.hoisted(() => vi.fn());
const updateThreadMock = vi.hoisted(() => vi.fn());
const sendMessageMock = vi.hoisted(() => vi.fn());
const getThreadMock = vi.hoisted(() => vi.fn());

vi.mock("@/api/channels", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/channels")>();
  return {
    ...actual,
    getThreadMessages: getThreadMessagesMock,
    getThread: getThreadMock,
    updateThread: updateThreadMock,
    sendMessage: sendMessageMock,
  };
});

// ── Import after mocking ─────────────────────────────────────────────────────

import { MessageThread } from "@/components/channels/MessageThread";

// ── Helpers ──────────────────────────────────────────────────────────────────

const buildThread = (overrides: Partial<ThreadRead> = {}): ThreadRead => ({
  id: "thread-1",
  channel_id: "ch-1",
  topic: "api-service — Build #1234",
  is_resolved: false,
  is_pinned: false,
  task_id: null,
  source_type: "user",
  source_ref: null,
  message_count: 0,
  last_message_at: null,
  last_message_preview: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  ...overrides,
});

const buildMessage = (overrides: Partial<ThreadMessageRead> = {}): ThreadMessageRead => ({
  id: `msg-${Math.random().toString(16).slice(2)}`,
  thread_id: "thread-1",
  sender_type: "user",
  sender_id: null,
  sender_name: "You",
  content: "Hello world",
  content_type: "text",
  event_metadata: null,
  is_edited: false,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  ...overrides,
});

const successMessagesResponse = (messages: ThreadMessageRead[]) =>
  Promise.resolve({
    data: messages,
    status: 200,
    headers: new Headers(),
  });

// ── Tests ────────────────────────────────────────────────────────────────────

describe("MessageThread", () => {
  beforeEach(() => {
    getThreadMessagesMock.mockReset();
    getThreadMock.mockReset();
    updateThreadMock.mockReset();
    sendMessageMock.mockReset();
    // Default: empty messages
    getThreadMessagesMock.mockResolvedValue({
      data: [],
      status: 200,
      headers: new Headers(),
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it("renders thread topic in the header", async () => {
    render(
      <MessageThread
        thread={buildThread({ topic: "Deploy #42 failed" })}
        boardId="board-1"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Deploy #42 failed")).toBeDefined();
    });
  });

  it("shows empty state when no messages", async () => {
    render(
      <MessageThread thread={buildThread()} boardId="board-1" />,
    );

    await waitFor(() => {
      expect(screen.getByText(/No messages yet/i)).toBeDefined();
    });
  });

  it("renders user message bubbles", async () => {
    const userMessage = buildMessage({
      sender_type: "user",
      sender_name: "Alice",
      content: "Hello from Alice",
    });
    getThreadMessagesMock.mockResolvedValue(
      await successMessagesResponse([userMessage]),
    );

    render(
      <MessageThread thread={buildThread()} boardId="board-1" />,
    );

    await waitFor(() => {
      expect(screen.getByText("Hello from Alice")).toBeDefined();
    });

    const bubble = screen.getByTestId("message-bubble-user");
    expect(bubble).toBeDefined();
  });

  it("renders agent message bubbles", async () => {
    const agentMessage = buildMessage({
      sender_type: "agent",
      sender_name: "Lethe",
      content: "I am investigating the issue",
    });
    getThreadMessagesMock.mockResolvedValue(
      await successMessagesResponse([agentMessage]),
    );

    render(
      <MessageThread thread={buildThread()} boardId="board-1" />,
    );

    await waitFor(() => {
      expect(screen.getByText("I am investigating the issue")).toBeDefined();
    });

    const bubble = screen.getByTestId("message-bubble-agent");
    expect(bubble).toBeDefined();
  });

  it("renders webhook event cards for webhook messages", async () => {
    const webhookMessage = buildMessage({
      sender_type: "webhook",
      content: "Build FAILED",
      content_type: "webhook_event",
      event_metadata: { severity: "error", build_number: "1234" },
    });
    getThreadMessagesMock.mockResolvedValue(
      await successMessagesResponse([webhookMessage]),
    );

    render(
      <MessageThread thread={buildThread()} boardId="board-1" />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("webhook-event-card")).toBeDefined();
    });
  });

  it("renders system messages centred", async () => {
    const systemMessage = buildMessage({
      sender_type: "system",
      content: "Thread was resolved",
      content_type: "text",
    });
    getThreadMessagesMock.mockResolvedValue(
      await successMessagesResponse([systemMessage]),
    );

    render(
      <MessageThread thread={buildThread()} boardId="board-1" />,
    );

    await waitFor(() => {
      expect(screen.getByText("Thread was resolved")).toBeDefined();
    });
  });

  it("shows the resolve button and calls updateThread when clicked", async () => {
    updateThreadMock.mockResolvedValue({
      data: buildThread({ is_resolved: true }),
      status: 200,
      headers: new Headers(),
    });

    render(
      <MessageThread thread={buildThread()} boardId="board-1" />,
    );

    await waitFor(() => expect(getThreadMessagesMock).toHaveBeenCalled());

    const resolveBtn = screen.getByTitle("Mark resolved");
    resolveBtn.click();

    await waitFor(() => {
      expect(updateThreadMock).toHaveBeenCalledWith("thread-1", {
        is_resolved: true,
      });
    });
  });

  it("renders LinkedTaskBadge when thread has task_id", async () => {
    render(
      <MessageThread
        thread={buildThread({ task_id: "task-abc" })}
        boardId="board-1"
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("linked-task-badge")).toBeDefined();
    });
  });
});
