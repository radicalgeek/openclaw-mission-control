"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpCircle,
  CheckCircle2,
  Eye,
  Pencil,
  RefreshCcw,
  Trash2,
} from "lucide-react";

import { Markdown } from "@/components/atoms/Markdown";
import { MpcAppResultCard } from "@/components/atoms/MpcAppResultCard";
import { McpAppRenderer } from "@/components/atoms/McpAppRenderer";
import { cn } from "@/lib/utils";
import {
  type PlanRead,
  type PlanMessage,
  chatWithPlan,
  updatePlan,
  deletePlan,
  getPlan,
  decomposePlan,
} from "@/api/plans";
import { PlanStatusBadge } from "./PlanStatusBadge";

// ─── Markdown editor toolbar ─────────────────────────────────────────────────

const SAVE_DEBOUNCE_MS = 1200;
const AGENT_POLL_INTERVAL_MS = 2000;
const AGENT_POLL_MAX_ATTEMPTS = 180;

type ContentMode = "preview" | "edit";

/** True when the last message is from the user and we're waiting for an agent reply. */
function isAwaitingAgentReply(msgs: PlanMessage[]): boolean {
  return msgs.length > 0 && msgs[msgs.length - 1].role === "user";
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({
  msg,
  boardId,
}: {
  msg: PlanMessage;
  boardId: string;
}) {
  const isUser = msg.role === "user";
  const meta = msg.metadata ?? null;
  const resourceUri =
    typeof meta?.resource_uri === "string" ? meta.resource_uri : null;
  const agentId = typeof meta?.agent_id === "string" ? meta.agent_id : null;
  const resourceHtml =
    typeof meta?.resource_html === "string" ? meta.resource_html : null;
  return (
    <div className={cn("flex flex-col gap-0.5", isUser && "items-end")}>
      <span className="text-[10px] text-slate-400 px-1">
        {isUser ? "You" : "Agent"}
      </span>
      <div
        className={cn(
          "rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "max-w-[85%] bg-[color:var(--accent)] text-[color:var(--accent-foreground)] rounded-br-sm"
            : "w-full bg-white border border-slate-200 text-slate-800 rounded-bl-sm",
        )}
      >
        {!isUser && msg.content_type === "mcp_app_result" ? (
          resourceUri && agentId ? (
            <McpAppRenderer
              boardId={boardId}
              agentId={agentId}
              resourceUri={resourceUri}
              resourceHtml={resourceHtml}
              fallbackContent={msg.content}
            />
          ) : (
            <MpcAppResultCard
              metadata={meta}
              fallbackContent={msg.content}
              variant="comment"
            />
          )
        ) : (
          <Markdown content={msg.content} variant="comment" />
        )}
      </div>
    </div>
  );
}

// ─── Chat composer ────────────────────────────────────────────────────────────

type ComposerProps = {
  onSend: (msg: string) => void;
  disabled?: boolean;
};

function ChatComposer({ onSend, disabled }: ComposerProps) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className="flex items-end gap-2 border-t border-slate-200 bg-white px-4 py-3">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        disabled={disabled}
        rows={2}
        placeholder={disabled ? "Agent is thinking…" : "Message the agent…"}
        className="flex-1 resize-none rounded-xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm focus:border-[color:var(--accent)] focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)] disabled:opacity-50"
      />
      <button
        onClick={submit}
        disabled={disabled || !text.trim()}
        className="mb-0.5 flex h-9 w-9 items-center justify-center rounded-full bg-[color:var(--accent)] text-[color:var(--accent-foreground)] transition hover:bg-[color:var(--accent-strong)] disabled:opacity-40"
        title="Send"
      >
        <ArrowUpCircle className="h-5 w-5" />
      </button>
    </div>
  );
}

// ─── Main PlanDetail component ────────────────────────────────────────────────

type Props = {
  boardId: string;
  plan: PlanRead;
  onPlanUpdated: (plan: PlanRead) => void;
  onPlanDeleted: () => void;
  startAgentPolling?: boolean;
  onAgentSettled?: (planId: string) => void;
};

export function PlanDetail({
  boardId,
  plan: initialPlan,
  onPlanUpdated,
  onPlanDeleted,
  startAgentPolling = false,
  onAgentSettled,
}: Props) {
  const [plan, setPlan] = useState<PlanRead>(initialPlan);
  const [contentMode, setContentMode] = useState<ContentMode>("preview");
  const [editContent, setEditContent] = useState(initialPlan.content);
  const [isEditing, setIsEditing] = useState(false);
  const [agentPendingContent, setAgentPendingContent] = useState<string | null>(
    null,
  );
  const [messages, setMessages] = useState<PlanMessage[]>(
    initialPlan.messages ?? [],
  );
  const [agentThinking, setAgentThinking] = useState(
    () => startAgentPolling && isAwaitingAgentReply(initialPlan.messages ?? []),
  );
  const [generating, setGenerating] = useState(false);
  const [generateMessage, setGenerateMessage] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [savePending, setSavePending] = useState(false);

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);

  // Sync when a different plan is selected
  useEffect(() => {
    setPlan(initialPlan);
    setEditContent(initialPlan.content);
    const msgs = initialPlan.messages ?? [];
    setMessages(msgs);
    setAgentThinking(startAgentPolling && isAwaitingAgentReply(msgs));
    setAgentPendingContent(null);
    setContentMode("preview");
    setIsEditing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPlan.id, startAgentPolling]);

  // Auto-scroll chat
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages, agentThinking]);

  // Debounced auto-save for manual edits
  const scheduleAutoSave = useCallback(
    (content: string) => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(async () => {
        setSavePending(true);
        try {
          const result = await updatePlan(boardId, plan.id, { content });
          if (result.status === 200) {
            setPlan(result.data);
            onPlanUpdated(result.data);
          }
        } finally {
          setSavePending(false);
        }
      }, SAVE_DEBOUNCE_MS);
    },
    [boardId, plan.id, onPlanUpdated],
  );

  // Poll for agent reply
  const markAgentSettled = useCallback(() => {
    setAgentThinking(false);
    onAgentSettled?.(plan.id);
  }, [onAgentSettled, plan.id]);

  const startPolling = useCallback(
    (baselineMessageCount = messages.length) => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      let attempts = 0;

      const poll = async () => {
        attempts++;
        try {
          const result = await getPlan(boardId, plan.id);
          if (result.status === 200) {
            const fresh = result.data;
            const freshCount = fresh.messages?.length ?? 0;
            const contentChanged = fresh.content !== plan.content;
            if (freshCount > baselineMessageCount || contentChanged) {
              setMessages(fresh.messages ?? []);
              // Update content unless user is editing
              if (!isEditing) {
                setPlan(fresh);
                setEditContent(fresh.content);
                onPlanUpdated(fresh);
              } else if (fresh.content !== plan.content) {
                setAgentPendingContent(fresh.content);
              }
              markAgentSettled();
              return;
            }
          }
        } catch {
          // ignore poll errors
        }
        if (attempts < AGENT_POLL_MAX_ATTEMPTS) {
          pollTimerRef.current = setTimeout(poll, AGENT_POLL_INTERVAL_MS);
        } else {
          markAgentSettled();
        }
      };
      pollTimerRef.current = setTimeout(poll, AGENT_POLL_INTERVAL_MS);
    },
    [
      boardId,
      plan.id,
      messages.length,
      isEditing,
      plan.content,
      onPlanUpdated,
      markAgentSettled,
    ],
  );

  // Only poll automatically for a plan that was submitted in this browser
  // session. Stored transcripts can end with a user message for many reasons
  // (gateway failure, timed-out agent, user navigation); merely loading that
  // state must not re-enter the "drafting" UX or disable chat.
  useEffect(() => {
    if (startAgentPolling && isAwaitingAgentReply(messages)) {
      startPolling(messages.length);
    }
    // Only run on plan switch / explicit local pending state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPlan.id, startAgentPolling]);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  // Send chat message
  const handleSend = async (message: string) => {
    const optimistic: PlanMessage = {
      role: "user",
      content: message,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    setAgentThinking(true);

    try {
      await chatWithPlan(boardId, plan.id, { message });
      startPolling(messages.length + 1);
    } catch {
      markAgentSettled();
    }
  };

  // Manual content edit
  const handleContentChange = (val: string) => {
    setEditContent(val);
    setIsEditing(true);
    scheduleAutoSave(val);
  };

  const handleAcceptAgentContent = async () => {
    if (!agentPendingContent) return;
    setEditContent(agentPendingContent);
    setAgentPendingContent(null);
    setSavePending(true);
    try {
      const result = await updatePlan(boardId, plan.id, {
        content: agentPendingContent,
      });
      if (result.status === 200) {
        setPlan(result.data);
        onPlanUpdated(result.data);
      }
    } finally {
      setSavePending(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteConfirm) {
      setDeleteConfirm(true);
      return;
    }
    await deletePlan(boardId, plan.id);
    onPlanDeleted();
  };

  const handleGenerateTasks = async () => {
    setGenerating(true);
    setGenerateMessage(null);
    try {
      const result = await decomposePlan(boardId, plan.id);
      if (result.status === 200) {
        setGenerateMessage(
          "Triager dispatched — backlog tickets will appear in Sprints → Backlog.",
        );
        const refreshed = await getPlan(boardId, plan.id);
        if (refreshed.status === 200) {
          setPlan(refreshed.data);
          onPlanUpdated(refreshed.data);
        }
      } else {
        setGenerateMessage("Failed to dispatch triager.");
      }
    } catch (err) {
      setGenerateMessage(
        err instanceof Error
          ? `Failed to dispatch triager: ${err.message}`
          : "Failed to dispatch triager.",
      );
    } finally {
      setGenerating(false);
    }
  };

  const isCompleted = plan.status === "completed";
  const isArchived = plan.status === "archived";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-6 py-3">
        <h2 className="flex-1 truncate text-base font-semibold text-slate-800">
          {plan.title}
        </h2>
        <PlanStatusBadge status={plan.status} />
        {isCompleted && plan.task_id && (
          <span className="rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-medium text-green-700">
            Task linked
          </span>
        )}
        {/* Toolbar buttons */}
        {!isArchived && !isCompleted && (
          <button
            onClick={handleGenerateTasks}
            disabled={generating || !plan.content}
            title={
              !plan.content
                ? "Plan has no content to decompose"
                : "Send this plan to the triager — tickets will land in Sprints → Backlog"
            }
            className="flex items-center gap-1.5 rounded-md bg-[color:var(--accent)] px-3 py-1.5 text-xs font-medium text-[color:var(--accent-foreground)] hover:bg-[color:var(--accent-strong)] transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            {generating ? "Generating…" : "Generate tasks"}
          </button>
        )}
        <button
          onClick={handleDelete}
          title={
            deleteConfirm
              ? "Click again to confirm"
              : isArchived
                ? "Permanently delete this plan"
                : "Archive plan"
          }
          className={cn(
            "flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition",
            deleteConfirm
              ? "bg-red-100 text-red-700 hover:bg-red-200"
              : isArchived
                ? "text-red-400 hover:bg-red-50"
                : "text-slate-500 hover:bg-slate-100",
          )}
        >
          <Trash2 className="h-3.5 w-3.5" />
          {deleteConfirm ? "Confirm delete" : isArchived ? "Delete" : ""}
        </button>
      </div>

      {/* Completed banner */}
      {isCompleted && (
        <div className="shrink-0 flex items-center gap-2 border-b border-green-200 bg-green-50 px-6 py-2 text-sm text-green-700">
          <CheckCircle2 className="h-4 w-4" />
          This plan is complete — the linked task has been marked done.
        </div>
      )}

      {/* Agent pending content notification */}
      {agentPendingContent && (
        <div className="shrink-0 flex items-center justify-between gap-2 border-b border-amber-200 bg-amber-50 px-6 py-2 text-sm text-amber-700">
          <span>
            The agent updated the plan content while you were editing.
          </span>
          <div className="flex gap-2">
            <button
              onClick={handleAcceptAgentContent}
              className="rounded px-2 py-0.5 text-xs font-medium bg-amber-200 hover:bg-amber-300 transition"
            >
              Accept agent version
            </button>
            <button
              onClick={() => setAgentPendingContent(null)}
              className="rounded px-2 py-0.5 text-xs font-medium hover:bg-amber-100 transition"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Main body: content panel + chat */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Left: plan content */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden border-r border-slate-200">
          {/* Content toolbar */}
          <div className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-4 py-2">
            <button
              onClick={() => setContentMode("preview")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition",
                contentMode === "preview"
                  ? "bg-slate-100 text-slate-700"
                  : "text-slate-500 hover:bg-slate-50",
              )}
            >
              <Eye className="h-3.5 w-3.5" />
              Preview
            </button>
            <button
              onClick={() => {
                setContentMode("edit");
                setIsEditing(true);
              }}
              disabled={isArchived || agentThinking}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition",
                contentMode === "edit"
                  ? "bg-slate-100 text-slate-700"
                  : "text-slate-500 hover:bg-slate-50",
                (isArchived || agentThinking) &&
                  "opacity-40 cursor-not-allowed",
              )}
            >
              <Pencil className="h-3.5 w-3.5" />
              Edit
            </button>
            {savePending && (
              <span className="ml-auto flex items-center gap-1 text-[11px] text-slate-400">
                <RefreshCcw className="h-3 w-3 animate-spin" />
                Saving…
              </span>
            )}
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto">
            {contentMode === "preview" ? (
              <div className="p-6 text-sm">
                {agentThinking && !plan.content ? (
                  <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
                    <div className="flex gap-1.5 text-[color:var(--text-quiet)]">
                      <span className="animate-bounce text-lg">●</span>
                      <span className="animate-bounce delay-100 text-lg">
                        ●
                      </span>
                      <span className="animate-bounce delay-200 text-lg">
                        ●
                      </span>
                    </div>
                    <p className="text-sm text-[color:var(--text-muted)]">
                      Agent is drafting your plan…
                    </p>
                    <p className="text-xs text-[color:var(--text-quiet)]">
                      Editing and chat are disabled until the first draft is
                      ready.
                    </p>
                  </div>
                ) : plan.content ? (
                  <Markdown content={plan.content} variant="description" />
                ) : (
                  <p className="italic text-[color:var(--text-quiet)]">
                    No content yet. Chat with the agent or switch to Edit mode
                    to start writing.
                  </p>
                )}
              </div>
            ) : (
              <textarea
                value={editContent}
                onChange={(e) => handleContentChange(e.target.value)}
                disabled={isArchived}
                className="h-full w-full resize-none border-none bg-transparent p-6 font-mono text-sm text-slate-800 focus:outline-none disabled:opacity-50"
                placeholder="Write your plan in Markdown…"
              />
            )}
          </div>
        </div>

        {/* Right: chat */}
        <div className="flex w-[340px] shrink-0 flex-col overflow-hidden bg-slate-50">
          <div className="flex items-center border-b border-slate-200 bg-white px-4 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Agent chat
            </span>
          </div>

          <div
            ref={chatContainerRef}
            className="flex-1 space-y-4 overflow-y-auto px-4 py-4"
          >
            {messages.length === 0 && !agentThinking && (
              <p className="text-center text-xs text-slate-400">
                Chat with the project agent to build your plan.
              </p>
            )}
            {messages.map((msg, i) => (
              <MessageBubble key={i} msg={msg} boardId={boardId} />
            ))}
            {agentThinking && (
              <div className="flex flex-col gap-0.5">
                <span className="text-[10px] text-slate-400 px-1">Agent</span>
                <div className="inline-flex items-center gap-1.5 rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-400">
                  <span className="animate-bounce">●</span>
                  <span className="animate-bounce delay-100">●</span>
                  <span className="animate-bounce delay-200">●</span>
                </div>
              </div>
            )}
            <div ref={chatBottomRef} />
          </div>

          {!isArchived && (
            <ChatComposer onSend={handleSend} disabled={agentThinking} />
          )}
        </div>
      </div>

      {generateMessage && (
        <div className="shrink-0 border-t border-slate-200 bg-[color:var(--accent-soft)] px-6 py-2 text-xs text-[color:var(--accent-text-on-soft)]">
          {generateMessage}
        </div>
      )}
    </div>
  );
}
