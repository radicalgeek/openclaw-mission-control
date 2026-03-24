"use client";

import { useRef, useState } from "react";
import { Hash, MessageCircle, Pin, Rss, Send } from "lucide-react";

import type { ChannelRead, ThreadRead } from "@/api/channels";
import { isAlertChannel } from "@/api/channels";
import { cn } from "@/lib/utils";

type FilterTab = "active" | "resolved" | "pinned";

type Props = {
  channel: ChannelRead;
  threads: ThreadRead[];
  selectedThreadId: string | null;
  onSelectThread: (thread: ThreadRead) => void;
  onCreateThread: (topic: string, content: string) => Promise<void>;
  isLoading?: boolean;
};

const formatRelativeTime = (value: string | null): string => {
  if (!value) return "—";
  const date = new Date(value);
  if (isNaN(date.getTime())) return "—";
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ago`;
};

// ── Post card — one thread shown as a Teams-style post ────────────────────────

function PostCard({
  thread,
  isSelected,
  onSelect,
}: {
  thread: ThreadRead;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      data-testid="thread-post-card"
      className={cn(
        "w-full rounded-xl border px-5 py-4 text-left transition-colors",
        isSelected
          ? "border-blue-300 bg-blue-50 ring-1 ring-blue-200"
          : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/80",
      )}
    >
      {/* Topic row */}
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {thread.is_pinned ? (
              <Pin className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-500" />
            ) : null}
            <p
              className={cn(
                "text-sm font-semibold leading-snug text-slate-900 line-clamp-1",
                isSelected && "text-blue-800",
              )}
            >
              {thread.topic}
            </p>
          </div>
          {thread.last_message_preview ? (
            <p className="mt-1 text-xs text-slate-500 line-clamp-2 leading-relaxed">
              {thread.last_message_preview}
            </p>
          ) : null}
        </div>
        <span className="mt-0.5 flex-shrink-0 text-[11px] text-slate-400">
          {formatRelativeTime(thread.last_message_at ?? thread.updated_at)}
        </span>
      </div>

      {/* Meta row */}
      <div className="mt-2.5 flex items-center gap-3 text-[11px] text-slate-400">
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            thread.is_resolved
              ? "bg-emerald-100 text-emerald-700"
              : "bg-slate-100 text-slate-600",
          )}
        >
          {thread.is_resolved ? "resolved" : "active"}
        </span>
        <span className="flex items-center gap-1">
          <MessageCircle className="h-3 w-3" />
          {thread.message_count}{" "}
          {thread.message_count === 1 ? "reply" : "replies"}
        </span>
      </div>
    </button>
  );
}

// ── Inline composer — expands into a full subject + body form ─────────────────

function InlineComposer({
  onCreate,
  disabled = false,
}: {
  onCreate: (topic: string, content: string) => Promise<void>;
  disabled?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [topic, setTopic] = useState("");
  const [body, setBody] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const topicRef = useRef<HTMLInputElement>(null);

  const handleExpand = () => {
    setExpanded(true);
    // Small delay so the element renders before we focus
    setTimeout(() => topicRef.current?.focus(), 0);
  };

  const handleCancel = () => {
    setExpanded(false);
    setTopic("");
    setBody("");
    setError(null);
  };

  const handleSubmit = async () => {
    if (!topic.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await onCreate(topic.trim(), body.trim());
      setTopic("");
      setBody("");
      setExpanded(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to post. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={handleExpand}
        disabled={disabled}
        className="w-full rounded-xl border border-dashed border-slate-300 px-4 py-3 text-left text-sm text-slate-400 transition hover:border-slate-400 hover:text-slate-500"
      >
        Start a new conversation…
      </button>
    );
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-white shadow-sm">
      <div className="px-4 pt-4">
        <input
          ref={topicRef}
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              // Move focus to body
              (e.currentTarget.closest(".rounded-xl")?.querySelector("textarea") as HTMLTextAreaElement | null)?.focus();
            }
            if (e.key === "Escape") handleCancel();
          }}
          placeholder="Subject"
          className="w-full border-0 text-sm font-semibold text-slate-900 placeholder-slate-400 outline-none"
        />
        <div className="mt-2 border-t border-slate-100 pt-3">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && e.ctrlKey) {
                e.preventDefault();
                void handleSubmit();
              }
              if (e.key === "Escape") handleCancel();
            }}
            placeholder="Write a message… (markdown supported, Ctrl+Enter to post)"
            rows={4}
            className="w-full resize-none border-0 text-sm text-slate-700 placeholder-slate-400 outline-none focus:outline-none"
          />
        </div>
      </div>

      {error ? <p className="px-4 pb-2 text-xs text-rose-600">{error}</p> : null}

      <div className="flex items-center justify-end gap-2 border-t border-slate-100 px-4 py-2">
        <button
          type="button"
          onClick={handleCancel}
          className="text-xs text-slate-500 hover:text-slate-700"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={isSubmitting || !topic.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition opacity-90 hover:opacity-100 disabled:opacity-40"
        >
          <Send className="h-3 w-3" />
          {isSubmitting ? "Posting…" : "Post"}
        </button>
      </div>
    </div>
  );
}

// ── ChannelFeed ────────────────────────────────────────────────────────────────

export function ChannelFeed({
  channel,
  threads,
  selectedThreadId,
  onSelectThread,
  onCreateThread,
  isLoading = false,
}: Props) {
  const [activeTab, setActiveTab] = useState<FilterTab>("active");
  const readonly = isAlertChannel(channel);

  const filteredThreads = threads
    .filter((t) => {
      if (activeTab === "active") return !t.is_resolved;
      if (activeTab === "resolved") return t.is_resolved;
      if (activeTab === "pinned") return t.is_pinned;
      return true;
    })
    .sort((a, b) => {
      if (a.is_pinned && !b.is_pinned) return -1;
      if (!a.is_pinned && b.is_pinned) return 1;
      const aTime = a.last_message_at ?? a.updated_at;
      const bTime = b.last_message_at ?? b.updated_at;
      return new Date(bTime).getTime() - new Date(aTime).getTime();
    });

  const TABS: { id: FilterTab; label: string }[] = [
    { id: "active", label: "Active" },
    { id: "resolved", label: "Resolved" },
    { id: "pinned", label: "Pinned" },
  ];

  const ChannelIcon = channel.channel_type === "alert" ? Rss : Hash;

  return (
    <div className="flex h-full flex-col">
      {/* Channel header */}
      <div className="border-b border-slate-200 px-6 py-4">
        <div className="flex items-center gap-2">
          <ChannelIcon className="h-4 w-4 flex-shrink-0 text-slate-500" />
          <p className="text-base font-semibold text-slate-900">{channel.name}</p>
        </div>
        {channel.description ? (
          <p className="mt-0.5 text-sm text-slate-500">{channel.description}</p>
        ) : null}

        {/* Filter tabs */}
        <div className="mt-3 flex w-fit gap-1 rounded-lg bg-slate-100 p-0.5">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                activeTab === tab.id
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Post feed */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-xl bg-slate-100" />
            ))}
          </div>
        ) : filteredThreads.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <MessageCircle className="mb-3 h-10 w-10 text-slate-200" />
            <p className="text-sm font-medium text-slate-500">
              {activeTab === "active"
                ? "No conversations yet"
                : activeTab === "resolved"
                  ? "No resolved conversations"
                  : "No pinned conversations"}
            </p>
            {!readonly && activeTab === "active" ? (
              <p className="mt-1 text-xs text-slate-400">Use the composer below to start one ↓</p>
            ) : null}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredThreads.map((thread) => (
              <PostCard
                key={thread.id}
                thread={thread}
                isSelected={selectedThreadId === thread.id}
                onSelect={() => onSelectThread(thread)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Inline composer */}
      {!readonly ? (
        <div className="border-t border-slate-200 px-6 py-4">
          <InlineComposer onCreate={onCreateThread} />
        </div>
      ) : null}
    </div>
  );
}
