"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Hash, Link2, Pencil, Plus, Rss, Trash2 } from "lucide-react";

import type { ChannelRead, ThreadRead } from "@/api/channels";
import {
  getBoardChannels,
  getChannelThreads,
  createThread,
  createChannel,
  deleteChannel,
} from "@/api/channels";
import { ApiError } from "@/api/mutator";
import { cn } from "@/lib/utils";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import {
  listAgentsApiV1AgentsGet,
  type listAgentsApiV1AgentsGetResponse,
} from "@/api/generated/agents/agents";
import { ThreadList } from "./ThreadList";
import { MessageThread } from "./MessageThread";
import { NewThreadModal } from "./NewThreadModal";
import { CreateChannelModal } from "./CreateChannelModal";
import { EditChannelModal } from "./EditChannelModal";
import { ChannelWebhookModal } from "./ChannelWebhookModal";

type Props = {
  boardId: string;
  currentUserName?: string;
};

type MobilePanel = "channels" | "threads" | "messages";

// ── Per-board channel cache ──────────────────────────────────────────────────
type BoardChannels = Record<string, ChannelRead[] | "loading" | "error">;

// ── Local-storage helpers for collapsed state ────────────────────────────────
const LS_KEY = "mc_channels_collapsed";
function readCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw) as string[]);
  } catch {
    return new Set();
  }
}
function writeCollapsed(s: Set<string>) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify([...s]));
  } catch {
    // ignore
  }
}

export function ChannelsLayout({ boardId, currentUserName = "You" }: Props) {
  const router = useRouter();

  // ── Boards ────────────────────────────────────────────────────────────────
  const boardsQuery = useListBoardsApiV1BoardsGet<listBoardsApiV1BoardsGetResponse, ApiError>(
    undefined,
    { query: { refetchOnMount: false } },
  );
  const allBoards =
    boardsQuery.data?.status === 200 ? (boardsQuery.data.data.items ?? []) : [];

  // ── Collapse state (per-board) ────────────────────────────────────────────
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  useEffect(() => {
    setCollapsed(readCollapsed());
  }, []);

  const toggleCollapsed = (bid: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(bid)) {
        next.delete(bid);
        // When expanding, load channels if not already cached
        if (!(bid in boardChannels.current)) {
          void loadBoardChannels(bid);
        }
      } else {
        next.add(bid);
      }
      writeCollapsed(next);
      return next;
    });
  };

  // ── Channel cache (all boards, lazy-loaded) ───────────────────────────────
  const boardChannels = useRef<BoardChannels>({});
  const [, forceUpdate] = useState(0);
  const rerender = () => forceUpdate((n) => n + 1);

  const loadBoardChannels = useCallback(async (bid: string) => {
    if (boardChannels.current[bid] === "loading") return;
    boardChannels.current[bid] = "loading";
    rerender();
    try {
      const result = await getBoardChannels(bid);
      if (result.status === 200) {
        boardChannels.current[bid] = Array.isArray(result.data) ? result.data : [];
      } else {
        boardChannels.current[bid] = "error";
      }
    } catch {
      boardChannels.current[bid] = "error";
    }
    rerender();
  }, []);

  // Load channels for the current board immediately, and for other visible
  // (non-collapsed) boards lazily on mount.
  useEffect(() => {
    if (!boardId) return;
    void loadBoardChannels(boardId);
  }, [boardId, loadBoardChannels]);

  useEffect(() => {
    for (const board of allBoards) {
      if (!collapsed.has(board.id) && !(board.id in boardChannels.current)) {
        void loadBoardChannels(board.id);
      }
    }
  }, [allBoards, collapsed, loadBoardChannels]);

  // ── Channel/thread/message selection ─────────────────────────────────────
  const currentBoardChannels: ChannelRead[] =
    Array.isArray(boardChannels.current[boardId])
      ? (boardChannels.current[boardId] as ChannelRead[])
      : [];

  const [selectedChannel, setSelectedChannel] = useState<ChannelRead | null>(null);
  const [threads, setThreads] = useState<ThreadRead[]>([]);
  const [isLoadingThreads, setIsLoadingThreads] = useState(false);
  const [selectedThread, setSelectedThread] = useState<ThreadRead | null>(null);

  // Auto-select first channel when channel list loads
  const autoSelected = useRef(false);
  useEffect(() => {
    if (autoSelected.current) return;
    if (currentBoardChannels.length > 0) {
      autoSelected.current = true;
      setSelectedChannel(currentBoardChannels[0]);
    }
  }, [currentBoardChannels]);

  // Reset auto-select on board change
  useEffect(() => {
    autoSelected.current = false;
    setSelectedChannel(null);
    setThreads([]);
    setSelectedThread(null);
  }, [boardId]);

  // ── Agent suggestions (for @mention) ─────────────────────────────────────
  const [agentNames, setAgentNames] = useState<string[]>([]);
  useEffect(() => {
    if (!boardId) return;
    listAgentsApiV1AgentsGet({ board_id: boardId, limit: 50 })
      .then((res: listAgentsApiV1AgentsGetResponse) => {
        if (res.status === 200) {
          const names = (res.data.items ?? []).map((a) => a.name).filter(Boolean) as string[];
          setAgentNames(names);
        }
      })
      .catch(() => {/* ignore */});
  }, [boardId]);

  // ── Thread loading ────────────────────────────────────────────────────────
  const loadThreads = useCallback(async (channelId: string) => {
    setIsLoadingThreads(true);
    setThreads([]);
    setSelectedThread(null);
    try {
      const result = await getChannelThreads(channelId, { limit: 100 });
      if (result.status === 200) {
        setThreads(Array.isArray(result.data) ? result.data : []);
      }
    } catch {
      // ignore, threads will be empty
    } finally {
      setIsLoadingThreads(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedChannel) return;
    void loadThreads(selectedChannel.id);
  }, [selectedChannel, loadThreads]);

  // ── New thread modal ──────────────────────────────────────────────────────
  const [isNewThreadModalOpen, setIsNewThreadModalOpen] = useState(false);
  const [isCreatingThread, setIsCreatingThread] = useState(false);
  const [createThreadError, setCreateThreadError] = useState<string | null>(null);

  const handleCreateThread = async (topic: string, content: string) => {
    if (!selectedChannel) return;
    setIsCreatingThread(true);
    setCreateThreadError(null);
    try {
      const result = await createThread(selectedChannel.id, { topic, content });
      if (result.status === 200 || result.status === 201) {
        setThreads((prev) => [result.data, ...prev]);
        setSelectedThread(result.data);
        setIsNewThreadModalOpen(false);
        setMobilePanel("messages");
      } else {
        setCreateThreadError("Unable to create thread.");
      }
    } catch (err) {
      setCreateThreadError(
        err instanceof ApiError ? err.message : "Unable to create thread.",
      );
    } finally {
      setIsCreatingThread(false);
    }
  };

  // ── Create channel modal ────────────────────────────────────────────────
  const [isCreateChannelModalOpen, setIsCreateChannelModalOpen] = useState(false);
  const [targetBoardForChannel, setTargetBoardForChannel] = useState<string | null>(null);

  const handleCreateChannel = async (data: { name: string; channel_type: "discussion" | "alert"; description: string }) => {
    const bid = targetBoardForChannel || boardId;
    const result = await createChannel(bid, data);
    if (result.status === 200 || result.status === 201) {
      // Reload channels for this board
      await loadBoardChannels(bid);
    } else {
      throw new Error("Failed to create channel. Please try again.");
    }
  };

  const handleDeleteChannel = async (channelId: string) => {
    if (!confirm("Delete this channel? This action cannot be undone.")) return;
    try {
      await deleteChannel(channelId);
      // Reload current board channels
      await loadBoardChannels(boardId);
      if (selectedChannel?.id === channelId) {
        setSelectedChannel(null);
        setThreads([]);
        setSelectedThread(null);
      }
    } catch {
      alert("Failed to delete channel. Please try again.");
    }
  };

  // ── Edit channel modal ──────────────────────────────────────────────────
  const [editingChannel, setEditingChannel] = useState<ChannelRead | null>(null);

  const handleChannelUpdated = (updated: ChannelRead) => {
    // Update the channel in the cache
    const cached = boardChannels.current[boardId];
    if (Array.isArray(cached)) {
      boardChannels.current[boardId] = cached.map((c) =>
        c.id === updated.id ? updated : c,
      );
      rerender();
    }
    if (selectedChannel?.id === updated.id) {
      setSelectedChannel(updated);
    }
  };

  // ── Channel webhook modal ───────────────────────────────────────────────
  const [webhookChannel, setWebhookChannel] = useState<ChannelRead | null>(null);

  const handleThreadUpdated = (updated: ThreadRead) => {
    setThreads((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    setSelectedThread(updated);
  };

  // ── Mobile navigation ─────────────────────────────────────────────────────
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("channels");

  const handleSelectChannel = (channel: ChannelRead, targetBoardId?: string) => {
    // If selecting from a different board, navigate first
    if (targetBoardId && targetBoardId !== boardId) {
      router.push(`/channels/${targetBoardId}`);
    }
    setSelectedChannel(channel);
    setSelectedThread(null);
    setMobilePanel("threads");
  };

  const handleSelectThread = (thread: ThreadRead) => {
    setSelectedThread(thread);
    setMobilePanel("messages");
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row overflow-hidden">

      {/* ── Discord-style left sidebar ──────────────────────────────────── */}
      <div
        className={cn(
          "flex-shrink-0 w-56 border-r border-slate-200 bg-white flex-col overflow-hidden",
          mobilePanel === "channels" ? "flex" : "hidden md:flex",
        )}
      >
        {/* Sidebar header */}
        <div className="px-4 py-3 border-b border-slate-200">
          <p className="text-xs font-bold uppercase tracking-widest text-slate-600">
            Channels
          </p>
        </div>

        {/* Board groups + channels */}
        <div className="flex-1 overflow-y-auto py-2">
          {boardsQuery.isLoading ? (
            <p className="px-4 py-2 text-xs text-slate-500">Loading…</p>
          ) : (
            allBoards.map((board) => {
              const isCurrentBoard = board.id === boardId;
              const isCollapsed = collapsed.has(board.id);
              const channelsState = boardChannels.current[board.id];
              const boardChList: ChannelRead[] = Array.isArray(channelsState)
                ? channelsState
                : [];
              const isLoadingChList = channelsState === "loading";

              return (
                <div key={board.id} className="mb-1">
                  {/* Board header (collapsible group) */}
                  <button
                    type="button"
                    onClick={() => toggleCollapsed(board.id)}
                    className={cn(
                      "flex w-full items-center gap-1.5 px-3 py-1.5 text-left transition-colors",
                      isCurrentBoard
                        ? "text-slate-900 hover:text-black"
                        : "text-slate-600 hover:text-slate-900",
                    )}
                  >
                    <ChevronDown
                      className={cn(
                        "h-3 w-3 flex-shrink-0 transition-transform",
                        isCollapsed && "-rotate-90",
                      )}
                    />
                    <span className="truncate text-xs font-bold uppercase tracking-wider">
                      {board.name}
                    </span>
                    {/* Add channel button */}
                    {isCurrentBoard && !isCollapsed && (
                      <Plus
                        className="ml-auto h-3.5 w-3.5 flex-shrink-0 opacity-0 group-hover:opacity-100 hover:text-slate-700"
                        onClick={(e) => {
                          e.stopPropagation();
                          setTargetBoardForChannel(board.id);
                          setIsCreateChannelModalOpen(true);
                        }}
                      />
                    )}
                  </button>

                  {/* Channel list under this board */}
                  {!isCollapsed && (
                    <div>
                      {isLoadingChList ? (
                        <p className="px-7 py-1 text-xs text-slate-400">Loading…</p>
                      ) : boardChList.length === 0 ? (
                        <p className="px-7 py-1 text-xs text-slate-400">No channels</p>
                      ) : (
                        boardChList.map((ch) => {
                          const isSelected =
                            selectedChannel?.id === ch.id && isCurrentBoard;
                          return (
                            <div
                              key={ch.id}
                              className={cn(
                                "group flex w-full items-center gap-2 rounded-md px-3 py-1 text-sm transition-colors",
                                "mx-1 w-[calc(100%-8px)]",
                                isSelected
                                  ? "bg-slate-200 text-slate-900 font-medium"
                                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                              )}
                            >
                              <button
                                type="button"
                                onClick={() => handleSelectChannel(ch, board.id)}
                                className="flex flex-1 items-center gap-2 text-left"
                              >
                              {ch.channel_type === "alert" ? (
                                <Rss className="h-3.5 w-3.5 flex-shrink-0" />
                              ) : (
                                <Hash className="h-3.5 w-3.5 flex-shrink-0" />
                              )}
                              <span className="truncate">{ch.name}</span>
                              {(ch.unread_count ?? 0) > 0 && (
                                <span className="ml-auto flex-shrink-0 rounded-full bg-blue-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                                  {ch.unread_count}
                                </span>
                              )}
                              </button>
                              {isCurrentBoard && (
                                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition">
                                  {ch.channel_type === "alert" && (
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setWebhookChannel(ch);
                                      }}
                                      className="rounded p-0.5 hover:text-blue-600"
                                      title="Configure webhook"
                                    >
                                      <Link2 className="h-3 w-3" />
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setEditingChannel(ch);
                                    }}
                                    className="rounded p-0.5 hover:text-slate-700"
                                    title="Edit channel"
                                  >
                                    <Pencil className="h-3 w-3" />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void handleDeleteChannel(ch.id);
                                    }}
                                    className="rounded p-0.5 hover:text-rose-600"
                                    title="Delete channel"
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── Middle panel: Thread list ───────────────────────────────────── */}
      <div
        className={cn(
          "flex-shrink-0 border-r border-slate-200 bg-white md:w-72 flex-col overflow-hidden",
          mobilePanel === "threads" ? "flex" : "hidden md:flex",
        )}
      >
        {/* Mobile back */}
        <button
          type="button"
          onClick={() => setMobilePanel("channels")}
          className="mb-2 flex items-center gap-1.5 px-3 pt-3 text-sm font-medium text-blue-600 md:hidden"
        >
          ← Channels
        </button>
        {selectedChannel ? (
          <ThreadList
            channel={selectedChannel}
            threads={threads}
            selectedThreadId={selectedThread?.id ?? null}
            onSelectThread={handleSelectThread}
            onNewThread={() => {
              setIsNewThreadModalOpen(true);
              setCreateThreadError(null);
            }}
            isLoading={isLoadingThreads}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center p-4 text-sm text-slate-500">
            Select a channel to see threads.
          </div>
        )}
      </div>

      {/* ── Right panel: Message thread ─────────────────────────────────── */}
      <div
        className={cn(
          "min-w-0 flex-1 bg-white flex-col overflow-hidden",
          mobilePanel === "messages" ? "flex" : "hidden md:flex",
        )}
      >
        {/* Mobile back */}
        <button
          type="button"
          onClick={() => setMobilePanel("threads")}
          className="mb-2 flex items-center gap-1.5 px-3 pt-3 text-sm font-medium text-blue-600 md:hidden"
        >
          ← {selectedChannel ? `#${selectedChannel.name}` : "Threads"}
        </button>
        {selectedThread ? (
          <MessageThread
            thread={selectedThread}
            boardId={boardId}
            currentUserName={currentUserName}
            agentSuggestions={agentNames}
            onThreadUpdated={handleThreadUpdated}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-slate-400">
            Select a thread to view messages.
          </div>
        )}
      </div>

      {/* New Thread modal */}
      {selectedChannel ? (
        <NewThreadModal
          channel={selectedChannel}
          open={isNewThreadModalOpen}
          onOpenChange={setIsNewThreadModalOpen}
          onCreate={handleCreateThread}
          isCreating={isCreatingThread}
          error={createThreadError}
        />
      ) : null}

      {/* Create Channel modal */}
      <CreateChannelModal
        isOpen={isCreateChannelModalOpen}
        onClose={() => setIsCreateChannelModalOpen(false)}
        onSubmit={handleCreateChannel}
      />

      {/* Edit Channel modal */}
      {editingChannel && (
        <EditChannelModal
          channel={editingChannel}
          isOpen={!!editingChannel}
          onClose={() => setEditingChannel(null)}
          onUpdated={(updated) => {
            handleChannelUpdated(updated);
            setEditingChannel(null);
          }}
        />
      )}

      {/* Webhook Configuration modal */}
      {webhookChannel && (
        <ChannelWebhookModal
          channel={webhookChannel}
          isOpen={!!webhookChannel}
          onClose={() => setWebhookChannel(null)}
        />
      )}
    </div>
  );
}
