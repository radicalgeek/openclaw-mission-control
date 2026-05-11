import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

// ── Mock the MCP API client ──────────────────────────────────────────────────
vi.mock("@/api/mcp", () => ({
  readMcpResource: vi.fn(),
  callMcpTool: vi.fn(),
}));

import {
  McpAppRenderer,
  mcpToolContentText,
} from "@/components/atoms/McpAppRenderer";
import { readMcpResource } from "@/api/mcp";

const DEFAULT_PROPS = {
  boardId: "board-1",
  agentId: "agent-1",
  resourceUri: "ui://mission-control/chart.html",
};

describe("McpAppRenderer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    // Make readMcpResource hang so we see the loading state
    vi.mocked(readMcpResource).mockReturnValue(new Promise(() => {}));
    render(<McpAppRenderer {...DEFAULT_PROPS} />);
    expect(screen.getByText("Loading app…")).toBeTruthy();
  });

  it("renders iframe when resourceHtml prop is provided", async () => {
    render(
      <McpAppRenderer
        {...DEFAULT_PROPS}
        resourceHtml="<html><body>chart</body></html>"
      />,
    );
    await waitFor(() => {
      expect(screen.queryByText("Loading app…")).toBeNull();
    });
    // iframe should be present (jsdom renders iframe as element)
    const iframe = document.querySelector("iframe");
    expect(iframe).toBeTruthy();
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts");
    // Should NOT call the gateway
    expect(readMcpResource).not.toHaveBeenCalled();
  });

  it("renders iframe when toolResult.resource_html is provided", async () => {
    const toolResult = {
      content: [{ type: "text" as const, text: "done" }],
      ui_meta: { resource_uri: "ui://mission-control/chart.html" },
      resource_html: "<html><body>from-tool</body></html>",
    };
    render(<McpAppRenderer {...DEFAULT_PROPS} toolResult={toolResult} />);
    await waitFor(() => {
      expect(screen.queryByText("Loading app…")).toBeNull();
    });
    expect(document.querySelector("iframe")).toBeTruthy();
    expect(readMcpResource).not.toHaveBeenCalled();
  });

  it("fetches resource from gateway when no pre-fetched HTML", async () => {
    vi.mocked(readMcpResource).mockResolvedValue({
      uri: "ui://mission-control/chart.html",
      mime_type: "text/html",
      text: "<html>fetched</html>",
    });
    render(<McpAppRenderer {...DEFAULT_PROPS} />);
    await waitFor(() => {
      expect(screen.queryByText("Loading app…")).toBeNull();
    });
    expect(readMcpResource).toHaveBeenCalledWith(
      "board-1",
      "agent-1",
      "ui://mission-control/chart.html",
    );
    expect(document.querySelector("iframe")).toBeTruthy();
  });

  it("shows error state with fallback when fetch fails", async () => {
    vi.mocked(readMcpResource).mockRejectedValue(new Error("gateway down"));
    render(
      <McpAppRenderer {...DEFAULT_PROPS} fallbackContent="fallback text" />,
    );
    await waitFor(() => {
      expect(screen.queryByText("Loading app…")).toBeNull();
    });
    expect(screen.getByText(/mcp-app error/)).toBeTruthy();
    expect(screen.getByText(/gateway down/)).toBeTruthy();
    // Fallback Markdown shown
    expect(screen.getByText("fallback text")).toBeTruthy();
  });

  it("shows error state without fallback when none provided", async () => {
    vi.mocked(readMcpResource).mockRejectedValue(new Error("bad"));
    render(<McpAppRenderer {...DEFAULT_PROPS} />);
    await waitFor(() => {
      expect(screen.queryByText("Loading app…")).toBeNull();
    });
    expect(screen.getByText(/mcp-app error/)).toBeTruthy();
  });
});

describe("mcpToolContentText", () => {
  it("returns joined text from text-type content", () => {
    const content = [
      { type: "text" as const, text: "line1" },
      { type: "text" as const, text: "line2" },
    ];
    expect(mcpToolContentText(content)).toBe("line1\nline2");
  });

  it("filters out non-text content", () => {
    const content = [
      { type: "image" as const, text: null },
      { type: "text" as const, text: "hello" },
    ];
    expect(mcpToolContentText(content)).toBe("hello");
  });

  it("returns empty string for empty input", () => {
    expect(mcpToolContentText([])).toBe("");
  });
});
