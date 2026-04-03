"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { CheckCircle, Pin, PinOff, Send, TicketPlus, X } from "lucide-react";
import type { ThreadMessageRead, ThreadRead } from "@/api/channels";
import { createTaskFromThread, getThreadMessages, sendMessage, updateThread } from "@/api/channels";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/atoms/Markdown";
import { WebhookEventCard } from "./WebhookEventCard";
import { LinkedTaskBadge } from "./LinkedTaskBadge";
import { ApiError } from "@/api/mutator";

type Props = {
  thread: ThreadRead;
  boardId: string;
  currentUserName?: string;
  agentSuggestions?: string[];
  onThreadUpdated?: (updated: ThreadRead) => void;
  onClose?: () => void;
};

const formatTime = (value: string): string => {
  const date = new Date(value);
  if (isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

function SystemMessage({ message }: { message: ThreadMessageRead }) {
  return (
    <div className="flex justify-center py-1">
      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
        {message.content}
      </span>
    </div>
  );
}

function MessageBubble({
  message,
  isCurrentUser,
}: {
  message: ThreadMessageRead;
  isCurrentUser: boolean;
}) {
  if (message.content_type === "webhook_event") {
    return (
      <div className="w-full">
        <WebhookEventCard message={message} />
        <p className="mt-1 text-right text-[10px] text-slate-400">
          {formatTime(message.created_at)}
        </p>
      </div>
    );
  }

  if (
    message.sender_type === "system" ||
    message.content_type === "system_notification"
  ) {
    return <SystemMessage message={message} />;
  }

  const isAgent =
    message.sender_type === "agent" ||
    message.content_type === "agent_response";

  return (
    <div
      className={cn(
        "flex flex-col",
        isCurrentUser ? "items-end" : "items-start",
      )}
      data-testid={`message-bubble-${message.sender_type}`}
    >
      {message.sender_name ? (
        <p
          className={cn(
            "mb-1 text-[11px] font-semibold",
            isAgent ? "text-teal-700" : "text-slate-500",
          )}
        >
          {message.sender_name}
        </p>
      ) : null}
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm",
          isCurrentUser
            ? "bg-[color:var(--accent)] text-white rounded-br-sm"
            : isAgent
              ? "bg-slate-100 text-slate-800 rounded-bl-sm ring-1 ring-slate-200"
              : "bg-white text-slate-900 rounded-bl-sm ring-1 ring-slate-200",
        )}
      >
        <div
          className={cn(
            "prose prose-sm max-w-none break-words leading-relaxed",
            isCurrentUser
              ? "prose-invert"
              : isAgent
                ? "prose-slate"
                : "prose-slate",
          )}
        >
          <Markdown content={message.content} variant="comment" />
        </div>
      </div>
      <p className="mt-0.5 text-[10px] text-slate-400">
        {formatTime(message.created_at)}
      </p>
    </div>
  );
}

type MentionDropdownProps = {
  suggestions: string[];
  filter: string;
  onSelect: (name: string) => void;
};

function MentionDropdown({ suggestions, filter, onSelect }: MentionDropdownProps) {
  const matches = suggestions.filter((s) =>
    s.toLowerCase().startsWith(filter.toLowerCase()),
  );
  if (matches.length === 0) return null;
  return (
    <div className="absolute bottom-full left-0 mb-1 w-48 rounded-lg border border-slate-200 bg-white shadow-lg">
      {matches.map((name) => (
        <button
          key={name}
          type="button"
          className="w-full px-3 py-2 text-left text-sm hover:bg-slate-50"
          onMouseDown={(e) => {
            e.preventDefault();
            onSelect(name);
          }}
        >
          @{name}
        </button>
      ))}
    </div>
  );
}

export function MessageThread({
  thread,
  boardId,
  currentUserName = "You",
  agentSuggestions = [],
  onThreadUpdated,
  onClose,
}: Props) {
  const [messages, setMessages] = useState<ThreadMessageRead[]>([]);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [composerText, setComposerText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [isUpdatingThread, setIsUpdatingThread] = useState(false);
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [createTaskError, setCreateTaskError] = useState<string | null>(null);
  const [mentionFilter, setMentionFilter] = useState<string | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [unreadWhileScrolledUp, setUnreadWhileScrolledUp] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);
  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = messagesContainerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const threadIdRef = useRef<string>(thread.id);
  const [currentThread, setCurrentThread] = useState<ThreadRead>(thread);
  const prevMessageCountRef = useRef(0);

  // Sync thread prop changes
  useEffect(() => {
    setCurrentThread(thread);
  }, [thread]);

  const loadMessages = useCallback(async (threadId: string) => {
    setIsLoadingMessages(true);
    setMessagesError(null);
    try {
      const result = await getThreadMessages(threadId, { limit: 100 });
      if (result.status === 200) {
        setMessages(Array.isArray(result.data) ? result.data : []);
      } else {
        setMessagesError("Unable to load messages.");
      }
    } catch (err) {
      setMessagesError(
        err instanceof ApiError ? err.message : "Unable to load messages.",
      );
    } finally {
      setIsLoadingMessages(false);
    }
  }, []);

  // Load on mount / thread change
  useEffect(() => {
    threadIdRef.current = thread.id;
    prevMessageCountRef.current = 0;
    setUnreadWhileScrolledUp(0);
    void loadMessages(thread.id);
  }, [thread.id, loadMessages]);

  // Smart scroll: only auto-scroll if user is near bottom
  useEffect(() => {
    const newCount = messages.length;
    const prevCount = prevMessageCountRef.current;
    prevMessageCountRef.current = newCount;

    if (newCount > prevCount) {
      // New messages arrived
      if (isNearBottom) {
        // User is at bottom → scroll down
        scrollToBottom();
        setUnreadWhileScrolledUp(0);
      } else {
        // User scrolled up → increment unread counter
        setUnreadWhileScrolledUp((prev) => prev + (newCount - prevCount));
      }
    }
  }, [messages, isNearBottom]);

  // Track scroll position
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      setIsNearBottom(distanceFromBottom < 100); // Within 100px of bottom
      if (distanceFromBottom < 50) {
        // User scrolled back to bottom
        setUnreadWhileScrolledUp(0);
      }
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  // Poll for new messages every 10 seconds
  useEffect(() => {
    const id = window.setInterval(() => {
      if (threadIdRef.current) {
        void loadMessages(threadIdRef.current);
      }
    }, 10_000);
    return () => window.clearInterval(id);
  }, [loadMessages]);

  const handleSend = useCallback(async () => {
    const trimmed = composerText.trim();
    if (!trimmed) return;
    // Optimistically clear and re-focus so the user can start the next message
    // immediately without waiting for the round-trip.
    setComposerText("");
    setSendError(null);
    setIsSending(true);
    try {
      const result = await sendMessage(thread.id, {
        content: trimmed,
      });
      if (result.status === 201) {
        setMessages((prev) => [...prev, result.data]);
        setTimeout(() => {
          scrollToBottom();
        }, 100);
      } else {
        // Restore text so the user can try again
        setComposerText(trimmed);
        setSendError("Unable to send message.");
      }
    } catch (err) {
      // Restore text so the user can try again
      setComposerText(trimmed);
      setSendError(
        err instanceof ApiError ? err.message : "Unable to send message.",
      );
    } finally {
      setIsSending(false);
      composerRef.current?.focus();
    }
  }, [composerText, thread.id]);

  const handleToggleResolved = useCallback(async () => {
    setIsUpdatingThread(true);
    try {
      const result = await updateThread(currentThread.id, {
        is_resolved: !currentThread.is_resolved,
      });
      if (result.status === 200) {
        setCurrentThread(result.data);
        onThreadUpdated?.(result.data);
      }
    } catch {
      // ignore — we'll show stale state
    } finally {
      setIsUpdatingThread(false);
    }
  }, [currentThread, onThreadUpdated]);

  const handleCreateTask = useCallback(async () => {
    setIsCreatingTask(true);
    setCreateTaskError(null);
    try {
      const result = await createTaskFromThread(currentThread.id);
      if (result.status === 200) {
        setCurrentThread(result.data);
        onThreadUpdated?.(result.data);
        // Reload messages so the system notification appears
        void loadMessages(currentThread.id);
      } else {
        setCreateTaskError("Unable to create task. Please try again.");
      }
    } catch {
      setCreateTaskError("Unable to create task. Please try again.");
    } finally {
      setIsCreatingTask(false);
    }
  }, [currentThread.id, onThreadUpdated, loadMessages]);

  const handleTogglePinned = useCallback(async () => {
    setIsUpdatingThread(true);
    try {
      const result = await updateThread(currentThread.id, {
        is_pinned: !currentThread.is_pinned,
      });
      if (result.status === 200) {
        setCurrentThread(result.data);
        onThreadUpdated?.(result.data);
      }
    } catch {
      // ignore
    } finally {
      setIsUpdatingThread(false);
    }
  }, [currentThread, onThreadUpdated]);

  const handleComposerKeyDown = (
    e: React.KeyboardEvent<HTMLTextAreaElement>,
  ) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
      return;
    }
    // Mention trigger
    const text = composerText;
    const pos = composerRef.current?.selectionStart ?? text.length;
    const before = text.slice(0, pos);
    const atIdx = before.lastIndexOf("@");
    if (e.key === "Escape") {
      setMentionFilter(null);
      return;
    }
    if (atIdx !== -1) {
      const fragment = before.slice(atIdx + 1);
      if (!fragment.includes(" ")) {
        setMentionFilter(fragment);
        return;
      }
    }
    setMentionFilter(null);
  };

  const handleComposerChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setComposerText(value);
    const pos = e.target.selectionStart ?? value.length;
    const before = value.slice(0, pos);
    const atIdx = before.lastIndexOf("@");
    if (atIdx !== -1) {
      const fragment = before.slice(atIdx + 1);
      if (!fragment.includes(" ")) {
        setMentionFilter(fragment);
        return;
      }
    }
    setMentionFilter(null);
  };

  const handleMentionSelect = (name: string) => {
    // Insert only the first word so we produce a clean single-token @mention.
    // The backend matches on first name, so "@Celeste" correctly targets
    // an agent named "Celeste Sunburst".
    const token = name.split(" ")[0] ?? name;
    const pos = composerRef.current?.selectionStart ?? composerText.length;
    const before = composerText.slice(0, pos);
    const atIdx = before.lastIndexOf("@");
    if (atIdx !== -1) {
      const after = composerText.slice(pos);
      const next = `${before.slice(0, atIdx)}@${token} ${after}`;
      setComposerText(next);
    }
    setMentionFilter(null);
    composerRef.current?.focus();
  };

  return (
    <div className="flex h-full flex-col">
      {/* Thread header */}
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-slate-900 leading-snug">
              {currentThread.topic}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                  currentThread.is_resolved
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-slate-100 text-slate-600",
                )}
              >
                {currentThread.is_resolved ? "resolved" : "active"}
              </span>
              {currentThread.is_pinned ? (
                <span className="flex items-center gap-1 text-[11px] text-amber-600">
                  <Pin className="h-3 w-3" /> Pinned
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex flex-shrink-0 items-center gap-1.5">
            {!currentThread.task_id ? (
              <button
                type="button"
                onClick={() => void handleCreateTask()}
                disabled={isCreatingTask}
                title="Create a task from this conversation"
                className="flex items-center gap-1 rounded-lg border border-[color:var(--accent)] bg-[color:var(--accent-soft)] px-2 py-1 text-xs font-medium text-[color:var(--accent-strong)] transition hover:bg-[color:var(--accent-soft)] disabled:opacity-50"
              >
                <TicketPlus className="h-3.5 w-3.5" />
                {isCreatingTask ? "Creating…" : "Create issue"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => void handleTogglePinned()}
              disabled={isUpdatingThread}
              title={currentThread.is_pinned ? "Unpin thread" : "Pin thread"}
              className="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition hover:bg-slate-50"
            >
              {currentThread.is_pinned ? (
                <PinOff className="h-3.5 w-3.5" />
              ) : (
                <Pin className="h-3.5 w-3.5" />
              )}
            </button>
            <button
              type="button"
              onClick={() => void handleToggleResolved()}
              disabled={isUpdatingThread}
              title={
                currentThread.is_resolved
                  ? "Re-open thread"
                  : "Mark resolved"
              }
              className={cn(
                "rounded-lg border p-1.5 transition",
                currentThread.is_resolved
                  ? "border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                  : "border-slate-200 text-slate-500 hover:bg-slate-50",
              )}
            >
              <CheckCircle className="h-3.5 w-3.5" />
            </button>
            {onClose ? (
              <button
                type="button"
                onClick={onClose}
                title="Close"
                className="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition hover:bg-slate-50"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        </div>
        {/* Linked task badge */}
        {currentThread.task_id ? (
          <div className="mt-2">
            <LinkedTaskBadge
              taskId={currentThread.task_id}
              boardId={boardId}
            />
          </div>
        ) : null}
        {createTaskError ? (
          <p className="mt-1 text-xs text-rose-600">{createTaskError}</p>
        ) : null}
      </div>

      {/* Message list */}
      <div ref={messagesContainerRef} className="relative flex-1 overflow-y-auto px-4 py-4">
        {isLoadingMessages && messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-slate-400">Loading messages…</p>
          </div>
        ) : messagesError ? (
          <div className="rounded-lg border border-slate-200 p-3 text-sm text-slate-600">
            {messagesError}
          </div>
        ) : messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-slate-400">No messages yet. Start the conversation.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((msg) => {
              const isCurrentUser =
                msg.sender_type === "user" &&
                (msg.sender_name === currentUserName || msg.sender_name === "");
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isCurrentUser={isCurrentUser}
                />
              );
            })}
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* New messages pill (floating above bottom when scrolled up) */}
        {unreadWhileScrolledUp > 0 && (
          <button
            type="button"
            onClick={() => {
              scrollToBottom();
              setUnreadWhileScrolledUp(0);
            }}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-[color:var(--accent)] px-4 py-2 text-sm font-medium text-white shadow-lg transition hover:bg-[color:var(--accent-strong)]"
          >
            {unreadWhileScrolledUp} new message{unreadWhileScrolledUp > 1 ? "s" : ""}
          </button>
        )}
      </div>

      {/* Composer */}
      <div className="border-t border-slate-200 px-4 py-3">
        {sendError ? (
          <p className="mb-2 text-xs text-rose-600">{sendError}</p>
        ) : null}
        <div className="relative flex items-end gap-2">
          {mentionFilter !== null && agentSuggestions.length > 0 ? (
            <MentionDropdown
              suggestions={agentSuggestions}
              filter={mentionFilter}
              onSelect={handleMentionSelect}
            />
          ) : null}
          <textarea
            ref={composerRef}
            value={composerText}
            onChange={handleComposerChange}
            onKeyDown={handleComposerKeyDown}
            placeholder="Write a message… (Enter to send, Shift+Enter for newline, @ to mention)"
            rows={2}
            disabled={isSending}
            className="flex-1 resize-none rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 placeholder-slate-400 shadow-sm outline-none transition focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)] disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void handleSend()}
            disabled={isSending || !composerText.trim()}
            className="flex-shrink-0 rounded-xl bg-[color:var(--accent)] p-2.5 text-white transition hover:bg-[color:var(--accent-strong)] disabled:opacity-40"
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
