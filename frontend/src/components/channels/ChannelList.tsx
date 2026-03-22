"use client";

import {
  AlertTriangle,
  Bell,
  Box,
  Code2,
  Flame,
  MessageCircle,
  Rocket,
  Server,
  TestTube,
  Wrench,
} from "lucide-react";

import type { ChannelRead } from "@/api/channels";
import { cn } from "@/lib/utils";

type Props = {
  channels: ChannelRead[];
  selectedChannelId: string | null;
  onSelectChannel: (channel: ChannelRead) => void;
  isLoading?: boolean;
};

const CHANNEL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  "build-alerts": Box,
  "deployment-alerts": Rocket,
  "test-run-alerts": TestTube,
  "production-alerts": Flame,
  development: Code2,
  devops: Server,
  testing: TestTube,
  architecture: Wrench,
  general: MessageCircle,
};

const DEFAULT_CHANNEL_ICON = Bell;

function ChannelRow({
  channel,
  isSelected,
  onSelect,
}: {
  channel: ChannelRead;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const Icon = CHANNEL_ICONS[channel.slug] ?? DEFAULT_CHANNEL_ICON;
  const unread = channel.unread_count ?? 0;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition",
        isSelected
          ? "bg-blue-100 text-blue-800 font-medium"
          : "text-slate-700 hover:bg-slate-100",
      )}
      aria-current={isSelected ? "page" : undefined}
      data-testid={`channel-row-${channel.channel_type}`}
    >
      <Icon
        className={cn(
          "h-4 w-4 flex-shrink-0",
          isSelected ? "text-blue-600" : "text-slate-400",
        )}
      />
      <span className="flex-1 truncate">#{channel.name}</span>
      {unread > 0 ? (
        <span
          className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white"
          data-testid="unread-badge"
        >
          {unread > 99 ? "99+" : unread}
        </span>
      ) : null}
    </button>
  );
}

export function ChannelList({
  channels,
  selectedChannelId,
  onSelectChannel,
  isLoading = false,
}: Props) {
  const alertChannels = channels.filter((c) => c.channel_type === "alert");
  const discussionChannels = channels.filter((c) => c.channel_type === "discussion");

  if (isLoading) {
    return (
      <div className="p-4">
        <div className="space-y-2">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-8 animate-pulse rounded-lg bg-slate-200"
            />
          ))}
        </div>
      </div>
    );
  }

  if (channels.length === 0) {
    return (
      <div className="p-4 text-center text-sm text-slate-500">
        <AlertTriangle className="mx-auto mb-2 h-6 w-6 text-slate-300" />
        <p>No channels available.</p>
        <p className="mt-1 text-xs text-slate-400">
          Channels are created automatically when webhooks arrive.
        </p>
      </div>
    );
  }

  return (
    <nav className="flex flex-col gap-4 p-3" aria-label="Channels">
      {alertChannels.length > 0 ? (
        <div>
          <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Alert Channels
          </p>
          <div className="space-y-0.5">
            {alertChannels.map((channel) => (
              <ChannelRow
                key={channel.id}
                channel={channel}
                isSelected={selectedChannelId === channel.id}
                onSelect={() => onSelectChannel(channel)}
              />
            ))}
          </div>
        </div>
      ) : null}
      {discussionChannels.length > 0 ? (
        <div>
          <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Discussion Channels
          </p>
          <div className="space-y-0.5">
            {discussionChannels.map((channel) => (
              <ChannelRow
                key={channel.id}
                channel={channel}
                isSelected={selectedChannelId === channel.id}
                onSelect={() => onSelectChannel(channel)}
              />
            ))}
          </div>
        </div>
      ) : null}
    </nav>
  );
}
