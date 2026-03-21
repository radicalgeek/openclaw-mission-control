import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WebhookEventCard } from "@/components/channels/WebhookEventCard";
import type { ThreadMessageRead, MessageSeverity } from "@/api/channels";

const buildWebhookMessage = (
  overrides: Partial<ThreadMessageRead> = {},
): ThreadMessageRead => ({
  id: `msg-${Math.random().toString(16).slice(2)}`,
  thread_id: "thread-1",
  sender_type: "webhook",
  sender_id: null,
  sender_name: "CI/CD Pipeline",
  content: "Build FAILED",
  content_type: "webhook_event",
  event_metadata: { severity: "error" },
  is_edited: false,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  ...overrides,
});

describe("WebhookEventCard", () => {
  it("renders the message content", () => {
    render(
      <WebhookEventCard message={buildWebhookMessage({ content: "Build FAILED" })} />,
    );

    expect(screen.getByText("Build FAILED")).toBeDefined();
  });

  it("renders info severity with blue border", () => {
    const { getByTestId } = render(
      <WebhookEventCard
        message={buildWebhookMessage({ event_metadata: { severity: "info" } })}
      />,
    );

    const card = getByTestId("webhook-event-card");
    expect(card.className).toContain("border-blue-300");
    expect(card.getAttribute("data-severity")).toBe("info");
  });

  it("renders warning severity with amber border", () => {
    const { getByTestId } = render(
      <WebhookEventCard
        message={buildWebhookMessage({ event_metadata: { severity: "warning" } })}
      />,
    );

    const card = getByTestId("webhook-event-card");
    expect(card.className).toContain("border-amber-300");
    expect(card.getAttribute("data-severity")).toBe("warning");
  });

  it("renders error severity with red border", () => {
    const { getByTestId } = render(
      <WebhookEventCard
        message={buildWebhookMessage({ event_metadata: { severity: "error" } })}
      />,
    );

    const card = getByTestId("webhook-event-card");
    expect(card.className).toContain("border-red-300");
    expect(card.getAttribute("data-severity")).toBe("error");
  });

  it("renders critical severity with stronger red border", () => {
    const { getByTestId } = render(
      <WebhookEventCard
        message={buildWebhookMessage({ event_metadata: { severity: "critical" } })}
      />,
    );

    const card = getByTestId("webhook-event-card");
    expect(card.className).toContain("border-red-500");
    expect(card.getAttribute("data-severity")).toBe("critical");
  });

  it("defaults to info severity when event_metadata is null", () => {
    const { getByTestId } = render(
      <WebhookEventCard
        message={buildWebhookMessage({ event_metadata: null })}
      />,
    );
    const card = getByTestId("webhook-event-card");
    expect(card.getAttribute("data-severity")).toBe("info");
  });

  it("renders metadata key-value pairs (excluding severity)", () => {
    render(
      <WebhookEventCard
        message={buildWebhookMessage({
          content: "Deploy finished",
          event_metadata: {
            severity: "info",
            environment: "production",
            build_number: "1234",
          },
        })}
      />,
    );

    expect(screen.getByText("Environment:")).toBeDefined();
    expect(screen.getByText("production")).toBeDefined();
    expect(screen.getByText("Build Number:")).toBeDefined();
    expect(screen.getByText("1234")).toBeDefined();
    // severity should NOT be shown as a metadata row
    expect(screen.queryByText("Severity:")).toBeNull();
  });

  it("renders a View link when event_metadata.url is present", () => {
    render(
      <WebhookEventCard
        message={buildWebhookMessage({
          event_metadata: {
            severity: "info",
            url: "https://ci.example.com/builds/42",
          },
        })}
      />,
    );

    const link = screen.getByRole("link", { name: /view/i });
    expect(link.getAttribute("href")).toBe("https://ci.example.com/builds/42");
  });

  it("does not render a View link when event_metadata.url is absent", () => {
    render(
      <WebhookEventCard
        message={buildWebhookMessage({ event_metadata: { status: "ok" } })}
      />,
    );

    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders correctly for each severity level", () => {
    const severities: MessageSeverity[] = ["info", "warning", "error", "critical"];
    for (const severity of severities) {
      const { getByTestId, unmount } = render(
        <WebhookEventCard
          message={buildWebhookMessage({
            event_metadata: { severity },
            content: `${severity} event`,
          })}
        />,
      );
      expect(getByTestId("webhook-event-card").getAttribute("data-severity")).toBe(severity);
      unmount();
    }
  });
});
