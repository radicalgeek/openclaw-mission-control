"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import {
  ArrowUpCircle,
  CheckCircle2,
  Eye,
  Pencil,
  RefreshCcw,
  Trash2,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
  type PlanRead,
  type PlanMessage,
  chatWithPlan,
  updatePlan,
  deletePlan,
  getPlan,
} from "@/api/plans";
import { PlanStatusBadge } from "./PlanStatusBadge";
import { PromoteToTaskModal } from "./PromoteToTaskModal";
import { promotePlan } from "@/api/plans";

// ─── Markdown editor toolbar ─────────────────────────────────────────────────

const SAVE_DEBOUNCE_MS = 1200;

type ContentMode = "preview" | "edit";

/** True when the last message is from the user and we're waiting for an agent reply. */
function isAwaitingAgentReply(msgs: PlanMessage[]): boolean {
  return msgs.length > 0 && msgs[msgs.length - 1].role === "user";
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: PlanMessage }) {
  const isUser = msg.role === "user";
  return (
    <div className={cn("flex flex-col gap-0.5", isUser && "items-end")}>
      <span className="text-[10px] text-slate-400 px-1">
        {isUser ? "You" : "Agent"}
      </span>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-orange-500 text-white rounded-br-sm"
            : "bg-white border border-slate-200 text-slate-800 rounded-bl-sm",
        )}
      >
        {msg.content}
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
        className="flex-1 resize-none rounded-xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm focus:border-orange-400 focus:outline-none focus:ring-1 focus:ring-orange-400 disabled:opacity-50"
      />
      <button
        onClick={submit}
        disabled={disabled || !text.trim()}
        className="mb-0.5 flex h-9 w-9 items-center justify-center rounded-full bg-orange-500 text-white transition hover:bg-orange-600 disabled:opacity-40"
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
};

export function PlanDetail({
  boardId,
  plan: initialPlan,
  onPlanUpdated,
  onPlanDeleted,
}: Props) {
  const [plan, setPlan] = useState<PlanRead>(initialPlan);
  const [contentMode, setContentMode] = useState<ContentMode>("preview");
  const [editContent, setEditContent] = useState(initialPlan.content);
  const [isEditing, setIsEditing] = useState(false);
  const [agentPendingContent, setAgentPendingContent] = useState<string | null>(null);
  const [messages, setMessages] = useState<PlanMessage[]>(
    initialPlan.messages ?? [],
  );
  const [agentThinking, setAgentThinking] = useState(
    () => isAwaitingAgentReply(initialPlan.messages ?? []),
  );
  const [showPromoteModal, setShowPromoteModal] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [savePending, setSavePending] = useState(false);

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  // Sync when a different plan is selected
  useEffect(() => {
    setPlan(initialPlan);
    setEditContent(initialPlan.content);
    const msgs = initialPlan.messages ?? [];
    setMessages(msgs);
    setAgentThinking(isAwaitingAgentReply(msgs));
    setAgentPendingContent(null);
    setContentMode("preview");
    setIsEditing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPlan.id]);

  // Auto-scroll chat
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, agentThinking]);

  // Auto-start polling when the plan loads with a pending agent reply
  // (e.g., immediately after creation with an initial prompt)
  useEffect(() => {
    if (isAwaitingAgentReply(messages)) {
      startPolling();
    }
    // Only run on plan switch, not every messages change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPlan.id]);

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
  const startPolling = useCallback(() => {
    let attempts = 0;
    const MAX_ATTEMPTS = 30;

    const poll = async () => {
      attempts++;
      try {
        const result = await getPlan(boardId, plan.id);
        if (result.status === 200) {
          const fresh = result.data;
          const freshCount = fresh.messages?.length ?? 0;
          const currentCount = messages.length;
          if (freshCount > currentCount) {
            setMessages(fresh.messages ?? []);
            // Update content unless user is editing
            if (!isEditing) {
              setPlan(fresh);
              setEditContent(fresh.content);
              onPlanUpdated(fresh);
            } else if (fresh.content !== plan.content) {
              setAgentPendingContent(fresh.content);
            }
            setAgentThinking(false);
            return;
          }
        }
      } catch {
        // ignore poll errors
      }
      if (attempts < MAX_ATTEMPTS) {
        pollTimerRef.current = setTimeout(poll, 2000);
      } else {
        setAgentThinking(false);
      }
    };
    pollTimerRef.current = setTimeout(poll, 2000);
  }, [boardId, plan.id, messages.length, isEditing, plan.content, onPlanUpdated]);

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
      startPolling();
    } catch {
      setAgentThinking(false);
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

  const handlePromote = async () => {
    setShowPromoteModal(true);
  };

  const handlePromoteConfirm = async (payload: {
    task_title?: string;
    task_priority?: string;
  }) => {
    const result = await promotePlan(boardId, plan.id, payload);
    if (result.status === 200) {
      setPlan(result.data);
      onPlanUpdated(result.data);
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
        {!isArchived && !isCompleted && !plan.task_id && (
          <button
            onClick={handlePromote}
            className="flex items-center gap-1.5 rounded-md bg-orange-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-600 transition"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            Promote to task
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
                (isArchived || agentThinking) && "opacity-40 cursor-not-allowed",
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
              <div className="prose prose-sm max-w-none p-6">
                {agentThinking && !plan.content ? (
                  <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
                    <div className="flex gap-1.5 text-slate-400">
                      <span className="animate-bounce text-lg">●</span>
                      <span className="animate-bounce delay-100 text-lg">●</span>
                      <span className="animate-bounce delay-200 text-lg">●</span>
                    </div>
                    <p className="text-sm text-slate-500">Agent is drafting your plan…</p>
                    <p className="text-xs text-slate-400">Editing and chat are disabled until the first draft is ready.</p>
                  </div>
                ) : plan.content ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
                    {plan.content}
                  </ReactMarkdown>
                ) : (
                  <p className="italic text-slate-400">
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

          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
            {messages.length === 0 && !agentThinking && (
              <p className="text-center text-xs text-slate-400">
                Chat with the board agent to build your plan.
              </p>
            )}
            {messages.map((msg, i) => (
              <MessageBubble key={i} msg={msg} />
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

      {showPromoteModal && (
        <PromoteToTaskModal
          plan={plan}
          onConfirm={handlePromoteConfirm}
          onClose={() => setShowPromoteModal(false)}
        />
      )}
    </div>
  );
}
