import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChannelList } from "@/components/channels/ChannelList";
import type { ChannelRead } from "@/api/channels";

const buildChannel = (
  overrides: Partial<ChannelRead> = {},
): ChannelRead => ({
  id: `ch-${Math.random().toString(16).slice(2)}`,
  board_id: "board-1",
  name: "general",
  slug: "general",
  channel_type: "discussion",
  description: "",
  is_archived: false,
  is_readonly: false,
  webhook_source_filter: null,
  position: 0,
  unread_count: 0,
  last_message_preview: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  ...overrides,
});

describe("ChannelList", () => {
  it("renders channels grouped into alert and discussion sections", () => {
    const channels: ChannelRead[] = [
      buildChannel({ name: "build-alerts", channel_type: "alert" }),
      buildChannel({ name: "general", channel_type: "discussion" }),
    ];

    render(
      <ChannelList
        channels={channels}
        selectedChannelId={null}
        onSelectChannel={vi.fn()}
      />,
    );

    // Both channels rendered
    expect(screen.getByText("#build-alerts")).toBeDefined();
    expect(screen.getByText("#general")).toBeDefined();

    // Group headers
    expect(screen.getByText("Alert Channels")).toBeDefined();
    expect(screen.getByText("Discussion Channels")).toBeDefined();
  });

  it("shows unread badge when unread_count > 0", () => {
    const channels: ChannelRead[] = [
      buildChannel({
        name: "build-alerts",
        channel_type: "alert",
        unread_count: 5,
      }),
    ];

    render(
      <ChannelList
        channels={channels}
        selectedChannelId={null}
        onSelectChannel={vi.fn()}
      />,
    );

    const badge = screen.getByTestId("unread-badge");
    expect(badge.textContent).toBe("5");
  });

  it("does not show unread badge when unread_count is 0", () => {
    const channels: ChannelRead[] = [
      buildChannel({ name: "general", channel_type: "discussion", unread_count: 0 }),
    ];

    render(
      <ChannelList
        channels={channels}
        selectedChannelId={null}
        onSelectChannel={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("unread-badge")).toBeNull();
  });

  it("shows 99+ for very large unread counts", () => {
    const channels: ChannelRead[] = [
      buildChannel({
        name: "production-alerts",
        channel_type: "alert",
        unread_count: 150,
      }),
    ];

    render(
      <ChannelList
        channels={channels}
        selectedChannelId={null}
        onSelectChannel={vi.fn()}
      />,
    );

    expect(screen.getByTestId("unread-badge").textContent).toBe("99+");
  });

  it("marks the selected channel with aria-current=page", () => {
    const channel = buildChannel({ name: "devops", channel_type: "discussion" });

    render(
      <ChannelList
        channels={[channel]}
        selectedChannelId={channel.id}
        onSelectChannel={vi.fn()}
      />,
    );

    const button = screen.getByTestId(`channel-row-devops`);
    expect(button.getAttribute("aria-current")).toBe("page");
  });

  it("shows empty state when no channels", () => {
    render(
      <ChannelList
        channels={[]}
        selectedChannelId={null}
        onSelectChannel={vi.fn()}
      />,
    );

    expect(screen.getByText("No channels available.")).toBeDefined();
  });

  it("shows loading skeleton when isLoading is true", () => {
    const { container } = render(
      <ChannelList
        channels={[]}
        selectedChannelId={null}
        onSelectChannel={vi.fn()}
        isLoading
      />,
    );

    // Loading skeleton divs have animate-pulse class
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("calls onSelectChannel when a channel is clicked", async () => {
    const channel = buildChannel({ name: "general", channel_type: "discussion" });
    const onSelect = vi.fn();

    render(
      <ChannelList
        channels={[channel]}
        selectedChannelId={null}
        onSelectChannel={onSelect}
      />,
    );

    screen.getByTestId("channel-row-general").click();
    expect(onSelect).toHaveBeenCalledWith(channel);
  });
});
