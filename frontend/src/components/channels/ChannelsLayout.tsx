"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Hash, MessageCircle, Plus, Rss, Trash2, User } from "lucide-react";

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
import type { AgentRead } from "@/api/generated/model/agentRead";
import { ThreadList } from "./ThreadList";
import { MessageThread } from "./MessageThread";
import { NewThreadModal } from "./NewThreadModal";
import { CreateChannelModal } from "./CreateChannelModal";

type Props = {
  boardId: string;
  currentUserName?: string;
};

type MobilePanel = "channels" | "threads" | "messages";

// ── Per-board channel cache ──────────────────────────────────────────────────
type BoardChannels = Record<string, ChannelRead[] | "loading" | "error">;

// ── Per-board agent cache ──────────────────────────────────────────────────
type BoardAgents = Record<string, AgentRead[] | "loading" | "error">;

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

  // ── Agent cache (all boards, lazy-loaded) ─────────────────────────────────
  const boardAgents = useRef<BoardAgents>({});

  const loadBoardAgents = useCallback(async (bid: string) => {
    if (boardAgents.current[bid] === "loading") return;
    boardAgents.current[bid] = "loading";
    rerender();
    try {
      const res: listAgentsApiV1AgentsGetResponse = await listAgentsApiV1AgentsGet({
        board_id: bid,
        limit: 100,
      });
      if (res.status === 200) {
        boardAgents.current[bid] = (res.data.items ?? []) as AgentRead[];
      } else {
        boardAgents.current[bid] = "error";
      }
    } catch {
      boardAgents.current[bid] = "error";
    }
    rerender();
  }, []);

  // Load channels + agents for the current board immediately, and for other
  // visible (non-collapsed) boards lazily on mount.
  useEffect(() => {
    if (!boardId) return;
    void loadBoardChannels(boardId);
    void loadBoardAgents(boardId);
  }, [boardId, loadBoardChannels, loadBoardAgents]);

  useEffect(() => {
    for (const board of allBoards) {
      if (!collapsed.has(board.id) && !(board.id in boardChannels.current)) {
        void loadBoardChannels(board.id);
      }
      if (!collapsed.has(board.id) && !(board.id in boardAgents.current)) {
        void loadBoardAgents(board.id);
      }
    }
  }, [allBoards, collapsed, loadBoardChannels, loadBoardAgents]);

  // ── Channel/thread/message selection ─────────────────────────────────────
  const currentBoardChannels: ChannelRead[] =
    Array.isArray(boardChannels.current[boardId])
      ? (boardChannels.current[boardId] as ChannelRead[])
      : [];

  const [selectedChannel, setSelectedChannel] = useState<ChannelRead | null>(null);
  const [threads, setThreads] = useState<ThreadRead[]>([]);
  const [isLoadingThreads, setIsLoadingThreads] = useState(false);
  const [selectedThread, setSelectedThread] = useState<ThreadRead | null>(null);

  // Auto-select first *regular* channel when channel list loads
  const autoSelected = useRef(false);
  useEffect(() => {
    if (autoSelected.current) return;
    const regularChannels = currentBoardChannels.filter((c) => c.channel_type !== "direct");
    if (regularChannels.length > 0) {
      autoSelected.current = true;
      setSelectedChannel(regularChannels[0]);
    }
  }, [currentBoardChannels]);

  // Reset auto-select on board change
  useEffect(() => {
    autoSelected.current = false;
    setSelectedChannel(null);
    setThreads([]);
    setSelectedThread(null);
  }, [boardId]);

  // ── @mention suggestions (derived from current board agents) ───────────────────
  const agentNames: string[] = (
    Array.isArray(boardAgents.current[boardId])
      ? (boardAgents.current[boardId] as AgentRead[])
      : []
  ).map((a) => a.name).filter(Boolean) as string[];

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

  const handleArchiveChannel = async (channelId: string) => {
    if (!confirm("Archive this channel? Threads will be preserved but the channel will be hidden.")) return;
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
      alert("Failed to archive channel. Please try again.");
    }
  };

  const handleThreadUpdated = (updated: ThreadRead) => {
    setThreads((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    setSelectedThread(updated);
  };

  // ── Direct messages ───────────────────────────────────────────────────────
  const [isDmLoading, setIsDmLoading] = useState<string | null>(null); // agentId being opened

  const handleOpenDM = async (agent: AgentRead, targetBoardId: string) => {
    setIsDmLoading(agent.id);
    try {
      // Check cache for an existing DM channel with this agent
      const cached = boardChannels.current[targetBoardId];
      const existing = Array.isArray(cached)
        ? cached.find(
            (c) => c.channel_type === "direct" && c.webhook_source_filter === agent.id,
          )
        : undefined;

      if (existing) {
        handleSelectChannel(existing, targetBoardId);
        return;
      }

      // Create a new DM channel (webhook_source_filter stores the agent UUID)
      const result = await createChannel(targetBoardId, {
        name: agent.name,
        channel_type: "direct",
        webhook_source_filter: agent.id,
        description: `Direct messages with ${agent.name}`,
      });

      if (result.status === 200 || result.status === 201) {
        await loadBoardChannels(targetBoardId);
        handleSelectChannel(result.data, targetBoardId);
      }
    } finally {
      setIsDmLoading(null);
    }
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
              const regularChannels = boardChList.filter((c) => c.channel_type !== "direct");
              const directChannels = boardChList.filter((c) => c.channel_type === "direct");
              const agentsState = boardAgents.current[board.id];
              const boardAgentList: AgentRead[] = Array.isArray(agentsState) ? agentsState : [];

              return (
                <div key={board.id} className="mb-1">
                  {/* Board header (collapsible group) */}
                  <div
                    className={cn(
                      "group flex w-full items-center gap-1.5 px-3 py-1.5 transition-colors",
                      isCurrentBoard
                        ? "text-slate-900"
                        : "text-slate-600",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => toggleCollapsed(board.id)}
                      className="flex flex-1 items-center gap-1.5 text-left hover:text-black min-w-0"
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
                    </button>
                    {/* Add channel button */}
                    {isCurrentBoard && !isCollapsed && (
                      <button
                        type="button"
                        onClick={() => {
                          setTargetBoardForChannel(board.id);
                          setIsCreateChannelModalOpen(true);
                        }}
                        className="ml-auto flex-shrink-0 rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                        title="Add channel"
                      >
                        <Plus className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>

                  {/* Expanded board content */}
                  {!isCollapsed && (
                    <div>
                      {/* Regular channels (discussion / alert) */}
                      {isLoadingChList ? (
                        <p className="px-7 py-1 text-xs text-slate-400">Loading…</p>
                      ) : regularChannels.length === 0 ? (
                        <p className="px-7 py-1 text-xs text-slate-400">No channels</p>
                      ) : (
                        regularChannels.map((ch) => {
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
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void handleArchiveChannel(ch.id);
                                  }}
                                  className="opacity-0 group-hover:opacity-100 hover:text-rose-600 transition"
                                  title="Archive channel"
                                >
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              )}
                            </div>
                          );
                        })
                      )}

                      {/* Members section */}
                      {boardAgentList.length > 0 && (
                        <div className="mt-2 mb-1">
                          <p className="px-3 pb-0.5 text-[10px] font-bold uppercase tracking-widest text-slate-400">
                            Members
                          </p>
                          {boardAgentList.map((agent) => {
                            const isActive = agent.status === "active";
                            return (
                              <button
                                key={agent.id}
                                type="button"
                                onClick={() => void handleOpenDM(agent, board.id)}
                                disabled={isDmLoading === agent.id}
                                title={`DM ${agent.name}`}
                                className={cn(
                                  "flex w-full items-center gap-2 rounded-md px-3 py-1 text-left text-sm transition-colors",
                                  "mx-1 w-[calc(100%-8px)]",
                                  "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                                  isDmLoading === agent.id && "opacity-50 cursor-wait",
                                )}
                              >
                                <span
                                  className={cn(
                                    "h-2 w-2 flex-shrink-0 rounded-full",
                                    isActive ? "bg-green-400" : "bg-slate-300",
                                  )}
                                />
                                <User className="h-3 w-3 flex-shrink-0 text-slate-400" />
                                <span className="truncate">{agent.name}</span>
                                {agent.is_board_lead && (
                                  <span className="ml-auto flex-shrink-0 text-[9px] font-bold uppercase text-slate-400">
                                    Lead
                                  </span>
                                )}
                              </button>
                            );
                          })}
                        </div>
                      )}

                      {/* Direct Messages section */}
                      {directChannels.length > 0 && (
                        <div className="mt-2 mb-1">
                          <p className="px-3 pb-0.5 text-[10px] font-bold uppercase tracking-widest text-slate-400">
                            Direct Messages
                          </p>
                          {directChannels.map((ch) => {
                            const isSelected =
                              selectedChannel?.id === ch.id && isCurrentBoard;
                            return (
                              <button
                                key={ch.id}
                                type="button"
                                onClick={() => handleSelectChannel(ch, board.id)}
                                className={cn(
                                  "flex w-full items-center gap-2 rounded-md px-3 py-1 text-left text-sm transition-colors",
                                  "mx-1 w-[calc(100%-8px)]",
                                  isSelected
                                    ? "bg-slate-200 text-slate-900 font-medium"
                                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                                )}
                              >
                                <MessageCircle className="h-3.5 w-3.5 flex-shrink-0" />
                                <span className="truncate">{ch.name}</span>
                                {(ch.unread_count ?? 0) > 0 && (
                                  <span className="ml-auto flex-shrink-0 rounded-full bg-blue-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                                    {ch.unread_count}
                                  </span>
                                )}
                              </button>
                            );
                          })}
                        </div>
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
    </div>
  );
}
