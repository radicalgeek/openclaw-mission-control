"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";

import type { ChannelRead, ThreadRead } from "@/api/channels";
import {
  getBoardChannels,
  getChannelThreads,
  createThread,
} from "@/api/channels";
import { ApiError } from "@/api/mutator";
import { cn } from "@/lib/utils";
import { ChannelList } from "./ChannelList";
import { ThreadList } from "./ThreadList";
import { MessageThread } from "./MessageThread";
import { NewThreadModal } from "./NewThreadModal";

type Props = {
  boardId: string;
  currentUserName?: string;
};

type MobilePanel = "channels" | "threads" | "messages";

export function ChannelsLayout({ boardId, currentUserName = "You" }: Props) {
  const [channels, setChannels] = useState<ChannelRead[]>([]);
  const [isLoadingChannels, setIsLoadingChannels] = useState(false);
  const [channelsError, setChannelsError] = useState<string | null>(null);

  const [selectedChannel, setSelectedChannel] = useState<ChannelRead | null>(null);
  const [threads, setThreads] = useState<ThreadRead[]>([]);
  const [isLoadingThreads, setIsLoadingThreads] = useState(false);

  const [selectedThread, setSelectedThread] = useState<ThreadRead | null>(null);

  const [isNewThreadModalOpen, setIsNewThreadModalOpen] = useState(false);
  const [isCreatingThread, setIsCreatingThread] = useState(false);
  const [createThreadError, setCreateThreadError] = useState<string | null>(null);

  // Mobile navigation state
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("channels");

  // Load channels for the board
  useEffect(() => {
    if (!boardId) return;
    let cancelled = false;
    setIsLoadingChannels(true);
    setChannelsError(null);
    getBoardChannels(boardId)
      .then((result) => {
        if (cancelled) return;
        if (result.status === 200) {
          const list = Array.isArray(result.data) ? result.data : [];
          setChannels(list);
          // Auto-select first channel
          if (list.length > 0) {
            setSelectedChannel(list[0]);
          }
        } else {
          setChannelsError("Unable to load channels.");
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setChannelsError(
          err instanceof ApiError ? err.message : "Unable to load channels.",
        );
      })
      .finally(() => {
        if (!cancelled) setIsLoadingChannels(false);
      });
    return () => { cancelled = true; };
  }, [boardId]);

  // Load threads when channel changes
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

  const handleSelectChannel = (channel: ChannelRead) => {
    setSelectedChannel(channel);
    setSelectedThread(null);
    setMobilePanel("threads");
  };

  const handleSelectThread = (thread: ThreadRead) => {
    setSelectedThread(thread);
    setMobilePanel("messages");
  };

  const handleNewThread = () => {
    setIsNewThreadModalOpen(true);
    setCreateThreadError(null);
  };

  const handleCreateThread = async (topic: string, content: string) => {
    if (!selectedChannel) return;
    setIsCreatingThread(true);
    setCreateThreadError(null);
    try {
      const result = await createThread(selectedChannel.id, {
        topic,
        content,
      });
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

  const handleThreadUpdated = (updated: ThreadRead) => {
    setThreads((prev) =>
      prev.map((t) => (t.id === updated.id ? updated : t)),
    );
    setSelectedThread(updated);
  };

  // Mobile back buttons
  const mobileBackButton = (label: string, onClick: () => void) => (
    <button
      type="button"
      onClick={onClick}
      className="mb-2 flex items-center gap-1.5 text-sm font-medium text-blue-600 md:hidden"
    >
      <ArrowLeft className="h-4 w-4" />
      {label}
    </button>
  );

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      {/* ── Left panel: Channel list ────────────────────────────────── */}
      <div
        className={cn(
          "flex-shrink-0 border-r border-slate-200 bg-white md:w-56",
          mobilePanel === "channels" ? "flex flex-col" : "hidden md:flex md:flex-col",
        )}
      >
        <div className="border-b border-slate-200 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Channels
          </p>
        </div>
        {channelsError ? (
          <div className="p-4 text-sm text-slate-600">{channelsError}</div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <ChannelList
              channels={channels}
              selectedChannelId={selectedChannel?.id ?? null}
              onSelectChannel={handleSelectChannel}
              isLoading={isLoadingChannels}
            />
          </div>
        )}
      </div>

      {/* ── Middle panel: Thread list ───────────────────────────────── */}
      <div
        className={cn(
          "flex-shrink-0 border-r border-slate-200 bg-white md:w-72",
          mobilePanel === "threads" ? "flex flex-col p-2 md:p-0" : "hidden md:flex md:flex-col",
        )}
      >
        {mobilePanel === "threads"
          ? mobileBackButton("Channels", () => setMobilePanel("channels"))
          : null}
        {selectedChannel ? (
          <ThreadList
            channel={selectedChannel}
            threads={threads}
            selectedThreadId={selectedThread?.id ?? null}
            onSelectThread={handleSelectThread}
            onNewThread={handleNewThread}
            isLoading={isLoadingThreads}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center p-4 text-sm text-slate-500">
            Select a channel to see threads.
          </div>
        )}
      </div>

      {/* ── Right panel: Message thread ─────────────────────────────── */}
      <div
        className={cn(
          "min-w-0 flex-1 bg-white",
          mobilePanel === "messages" ? "flex flex-col p-2 md:p-0" : "hidden md:flex md:flex-col",
        )}
      >
        {mobilePanel === "messages"
          ? mobileBackButton(
              selectedChannel ? `#${selectedChannel.name}` : "Threads",
              () => setMobilePanel("threads"),
            )
          : null}
        {selectedThread ? (
          <MessageThread
            thread={selectedThread}
            boardId={boardId}
            currentUserName={currentUserName}
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
    </div>
  );
}
