"use client";

import { useState } from "react";
import { MessageCircle, Pin, Plus } from "lucide-react";

import type { ChannelRead, ThreadRead } from "@/api/channels";
import { isAlertChannel } from "@/api/channels";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type FilterTab = "active" | "resolved" | "pinned";

type Props = {
  channel: ChannelRead;
  threads: ThreadRead[];
  selectedThreadId: string | null;
  onSelectThread: (thread: ThreadRead) => void;
  onNewThread: () => void;
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

function ThreadRow({
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
      className={cn(
        "flex w-full flex-col gap-1.5 rounded-lg px-3 py-2.5 text-left transition",
        isSelected
          ? "bg-blue-50 ring-1 ring-blue-200"
          : "hover:bg-slate-50",
      )}
      data-testid="thread-row"
    >
      <div className="flex items-start gap-2">
        {thread.is_pinned ? (
          <Pin className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-500" aria-label="Pinned" />
        ) : null}
        <p
          className={cn(
            "flex-1 text-sm font-semibold leading-snug text-slate-900 line-clamp-2",
            isSelected && "text-blue-800",
          )}
        >
          {thread.topic}
        </p>
        <span className="mt-0.5 flex-shrink-0 text-[11px] text-slate-400">
          {formatRelativeTime(thread.last_message_at ?? thread.updated_at)}
        </span>
      </div>
      {thread.last_message_preview ? (
        <p className="text-xs text-slate-500 line-clamp-1">
          {thread.last_message_preview}
        </p>
      ) : null}
      <div className="flex items-center gap-2 text-[11px] text-slate-400">
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
        <span className="flex items-center gap-0.5">
          <MessageCircle className="h-3 w-3" />
          {thread.message_count}
        </span>
      </div>
    </button>
  );
}

export function ThreadList({
  channel,
  threads,
  selectedThreadId,
  onSelectThread,
  onNewThread,
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
      // Pinned first
      if (a.is_pinned && !b.is_pinned) return -1;
      if (!a.is_pinned && b.is_pinned) return 1;
      // Then by last message descending
      const aTime = a.last_message_at ?? a.updated_at;
      const bTime = b.last_message_at ?? b.updated_at;
      return new Date(bTime).getTime() - new Date(aTime).getTime();
    });

  const TABS: { id: FilterTab; label: string }[] = [
    { id: "active", label: "Active" },
    { id: "resolved", label: "Resolved" },
    { id: "pinned", label: "Pinned" },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900">
              #{channel.name}
            </p>
            {channel.description ? (
              <p className="mt-0.5 truncate text-xs text-slate-500">
                {channel.description}
              </p>
            ) : null}
          </div>
          {!readonly ? (
            <Button
              size="sm"
              onClick={onNewThread}
              className="flex-shrink-0 gap-1.5"
            >
              <Plus className="h-3.5 w-3.5" />
              New thread
            </Button>
          ) : null}
        </div>
        {/* Filter tabs */}
        <div className="mt-3 flex gap-1 rounded-lg bg-slate-100 p-0.5">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex-1 rounded-md px-2 py-1 text-xs font-medium transition-colors",
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

      {/* Thread list */}
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="space-y-2 p-2">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg bg-slate-100"
              />
            ))}
          </div>
        ) : filteredThreads.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <MessageCircle className="mb-2 h-8 w-8 text-slate-200" />
            <p className="text-sm text-slate-500">
              {activeTab === "active"
                ? "No active threads."
                : activeTab === "resolved"
                  ? "No resolved threads."
                  : "No pinned threads."}
            </p>
            {!readonly && activeTab === "active" ? (
              <button
                type="button"
                onClick={onNewThread}
                className="mt-2 text-xs font-semibold text-blue-600 hover:underline"
              >
                Start the first thread →
              </button>
            ) : null}
          </div>
        ) : (
          <div className="space-y-1">
            {filteredThreads.map((thread) => (
              <ThreadRow
                key={thread.id}
                thread={thread}
                isSelected={selectedThreadId === thread.id}
                onSelect={() => onSelectThread(thread)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
